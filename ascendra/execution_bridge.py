"""Outbound Sites executor. Credentials arrive only through a stdin JSON object.

The worker uses its explicitly configured local Ollama model, never the visitor's
router/API keys. This process is not permanent hosting: its lifetime is bounded
to 24 hours and its machine must remain available. No production worker is
started by importing this module.
"""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .execution_queue import ExecutionQueue
from .studio_projects import ALLOWED_FILES, MAX_FILE_BYTES, validate_artifact_files


class FenceLost(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SitesTransport:
    def __init__(self, site, service_token, bridge_token):
        self.site = site.rstrip('/')
        parsed = urlsplit(self.site)
        if (parsed.scheme != 'https' or not parsed.hostname or
                not parsed.hostname.endswith('.chatgpt.site') or parsed.path or
                parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment):
            raise ValueError('Expected an HTTPS Sites origin')
        if any(not isinstance(v, str) or not v or '\r' in v or '\n' in v
               for v in (service_token, bridge_token)):
            raise ValueError('Invalid service credentials')
        self.headers = {'Content-Type': 'application/json',
                        'OAI-Sites-Authorization': 'Bearer ' + service_token,
                        'Authorization': 'Bearer ' + bridge_token}
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, action, payload):
        if action not in {'claim', 'heartbeat', 'checkpoint', 'result', 'followup-claim', 'followup-result', 'followup-heartbeat'}:
            raise ValueError('Unknown bridge action')
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > 700000:
            raise ValueError('Bridge request too large')
        request = urllib.request.Request(self.site + '/api/execution/bridge/' + action,
                                         data=encoded, headers=self.headers)
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(1048577)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 409):
                raise FenceLost('Remote execution authorization or fence rejected') from None
            raise RuntimeError('Remote transport unavailable') from None
        if len(raw) > 1048576:
            raise ValueError('Bridge response too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Invalid bridge response')
        return result


def terminate_group(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
    except ProcessLookupError:
        pass


def worker_environment():
    """Do not pass arbitrary parent credentials to local worker subprocesses."""
    return {k: v for k, v in os.environ.items() if k in {
        'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'HTTPS_PROXY', 'HTTP_PROXY',
        'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE',
        'ASCENDRA_PLAYWRIGHT_PACKAGE', 'ASCENDRA_CHROMIUM', 'ASCENDRA_MAX_WORKERS'}}


def bounded_artifact(directory, allowed_root):
    directory, allowed_root = Path(directory), Path(allowed_root).resolve()
    if directory.is_symlink() or not directory.resolve().is_relative_to(allowed_root):
        raise ValueError('Artifact outside worker storage')
    files = []
    for name in ALLOWED_FILES:
        path = directory / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('Invalid artifact file')
        content = path.read_bytes().decode('utf-8')
        if not content:
            raise ValueError('Empty artifact file')
        files.append({'path': name, 'content': content})
    validate_artifact_files(files)
    return files


class ExecutionBridge:
    """Coordinates one remote lease and an injectable durable local runner.

runner.prepare(job)->local_id is idempotent; start(local_id)->Popen or None for
terminal jobs; progress(local_id)->bounded summary; result(local_id)->remote
result envelope; cancel(local_id) revokes local work. No credentials reach it.
"""
    def __init__(self, transport, runner, *, worker_id=None, clock=time.time,
                 sleep=time.sleep, stopping=lambda: False, terminate=terminate_group):
        self.transport, self.runner = transport, runner
        self.worker_id = worker_id or 'worker_' + uuid.uuid4().hex
        self.clock, self.sleep, self.stopping, self.terminate = clock, sleep, stopping, terminate

    def run_once(self):
        job = self.transport('claim', {'worker_id': self.worker_id}).get('job')
        if not job:
            return 'idle'
        fence = {'id': job['id'], 'lease_token': job['lease_token']}
        expires = job['lease_expires_at'] / 1000
        sequence = job.get('checkpoint_seq', 0)
        local_id, process = None, None
        last_progress = None

        def heartbeat():
            nonlocal expires
            if self.stopping() or self.clock() >= expires - 6:
                raise FenceLost('Stopped or remote lease too near expiry')
            response = self.transport('heartbeat', fence)
            if response.get('accepted') is not True or response.get('stop_requested'):
                raise FenceLost('Remote fence lost')
            expires = response['lease_expires_at'] / 1000

        def checkpoint():
            nonlocal sequence, last_progress
            progress = {'local_id': local_id, 'progress': self.runner.progress(local_id)}
            encoded = json.dumps(progress, sort_keys=True, allow_nan=False)
            if len(encoded.encode()) > 100000:
                raise ValueError('Local progress too large')
            if encoded == last_progress:
                return
            response = self.transport('checkpoint', {**fence, 'expected_seq': sequence,
                                                      'checkpoint': progress})
            if response.get('accepted') is not True:
                raise FenceLost('Checkpoint fence lost')
            sequence = response['checkpoint_seq']
            last_progress = encoded

        try:
            heartbeat()
            local_id = self.runner.prepare(job)
            checkpoint()
            process = self.runner.start(local_id)
            next_heartbeat = self.clock() + 8
            while process is not None:
                if self.stopping() or self.clock() >= expires - 6:
                    raise FenceLost('Stopped or lease expired')
                if self.clock() >= next_heartbeat:
                    try:
                        heartbeat()
                        checkpoint()
                    except FenceLost:
                        raise
                    except Exception:
                        # Unknown response: do not assume lease renewal. Retain
                        # the old deadline and stop before it if retries fail.
                        pass
                    next_heartbeat = self.clock() + 2
                if process.poll() is not None:
                    if not hasattr(self.runner, 'finished') or self.runner.finished(local_id):
                        break
                    self.sleep(1)
                    process = self.runner.start(local_id)
                self.sleep(0.25)
            heartbeat()  # Never upload after a stale lease, even if local work passed.
            checkpoint()
            output = self.runner.result(local_id)
            accepted = self.transport('result', {**fence, **output})
            if accepted.get('accepted') is not True:
                raise FenceLost('Result fence lost')
            return output['status']
        except BaseException as exc:
            if local_id is not None:
                self.runner.cancel(local_id)
            if process is not None:
                self.terminate(process)
            if local_id is None and isinstance(exc, Exception) and not isinstance(exc, FenceLost):
                heartbeat()
                response = self.transport('result', {**fence, 'status': 'failed', 'result': {
                    'error_type': type(exc).__name__, 'reason': 'local_admission_failed',
                    'report': {'passed': False, 'checks': []}, 'published': False}})
                if response.get('accepted') is True:
                    return 'failed'
            raise

    def run_followup_once(self):
        """Separate opted-in one-call research lease; never holds a project lease."""
        remote = self.transport('followup-claim', {'worker_id': self.worker_id}).get('followup')
        if not remote:
            return 'idle'
        fence = {'id': remote['id'], 'lease_token': remote['lease_token']}
        end = min(remote['lease_expires_at'], remote['deadline_at']) / 1000 - 8
        process, local_id = None, None
        try:
            if self.stopping() or self.clock() >= end:
                raise FenceLost('Followup lease unavailable')
            local_id = self.runner.prepare_followup(remote)
            process = self.runner.start_followup(local_id)
            next_check = self.clock() + 2
            while process is not None:
                if self.stopping() or self.clock() >= end:
                    raise FenceLost('Followup stopped or time budget exhausted')
                if self.clock() >= next_check:
                    response = self.transport('followup-heartbeat', fence)
                    if response.get('accepted') is not True or response.get('stop_requested'):
                        raise FenceLost('Followup cancelled or fenced')
                    # Check only; research deadline is never extended.
                    next_check = self.clock() + 2
                if process.poll() is not None:
                    if not hasattr(self.runner, 'followup_finished') or self.runner.followup_finished(local_id):
                        break
                    self.sleep(1)
                    process = self.runner.start_followup(local_id)
                self.sleep(.25)
            if self.stopping() or self.clock() >= end:
                raise FenceLost('Followup publication deadline exceeded')
            outcome = self.runner.followup_result(local_id)
            response = self.transport('followup-result', {**fence, **outcome})
            if response.get('accepted') is not True:
                raise FenceLost('Followup result rejected')
            return outcome['status']
        except BaseException as exc:
            if local_id is not None:
                self.runner.cancel_followup(local_id)
            if process is not None:
                self.terminate(process)
            if (isinstance(exc, Exception) and not isinstance(exc, FenceLost)
                    and not self.stopping() and self.clock() < end):
                self.transport('followup-result', {**fence, 'status': 'failed'})
            raise


class LocalRunner:
    """One persistent SQLite queue per remote job, stable across bridge restarts."""
    def __init__(self, data, model='qwen2.5-coder:7b'):
        self.data = Path(data).absolute()
        if any(p.is_symlink() for p in (self.data, *self.data.parents)):
            raise ValueError('Symlink worker storage forbidden')
        if not isinstance(model, str) or not model or len(model) > 200 or 'cloud' in model.lower():
            raise ValueError('Installed local model required')
        self.model, self.jobs, self.followups = model, {}, {}
        self.data.mkdir(parents=True, exist_ok=True)

    def prepare(self, remote):
        from .execution_cli import enqueue
        remote_id = remote['id']
        # A digest is a stable path and idempotency key, never a supplied path.
        key = hashlib.sha256(remote_id.encode()).hexdigest()
        folder = self.data / key
        if any(p.is_symlink() for p in (folder, *folder.parents)):
            raise ValueError('Symlink recovery storage forbidden')
        prior_local = (remote.get('checkpoint') or {}).get('local_id')
        if prior_local and not (folder / 'execution.sqlite3').exists():
            raise ValueError('Recovery storage unavailable; refusing duplicate generation')
        queue = ExecutionQueue(folder / 'execution.sqlite3')
        if prior_local:
            queue.get(prior_local)  # Missing journal is not permission to regenerate.
        snapshot = remote['snapshot']
        if snapshot.get('mode', 'project') != 'project':
            raise ValueError('Only static project execution is supported')
        source = snapshot.get('proposal') or snapshot.get('brief')
        if not isinstance(source, dict):
            raise ValueError('Missing project description')
        description = '\n'.join(str(source.get(k, '')) for k in
                                ('title', 'description', 'acceptance_criteria'))
        contract = snapshot.get('verification_contract')
        if contract is None:
            contract = {'version': 1, 'scenarios': [{'name': 'Smoke only: page renders',
                'steps': [{'action': 'expect_visible', 'selector': 'body'}]}]}
        budget = remote['budget']
        calls = min(budget['max_calls'], 21)
        strategy = 'planned' if min(calls, budget['max_tokens'] // 20480) >= 2 else 'sequential'
        job = enqueue(queue, owner='sites_bridge', key=key, description=description,
                      contract=contract, max_calls=calls,
                      max_repairs=min(budget['max_repairs'], 20),
                      max_seconds=budget['max_seconds'], model=self.model,
                      max_tokens=budget['max_tokens'], max_agents=budget['max_agents'], strategy=strategy)
        self.jobs[job['id']] = (queue, folder, remote)
        return job['id']

    def start(self, local_id):
        queue, folder, _ = self.jobs[local_id]
        if queue.get(local_id)['state'] in {'completed', 'failed', 'cancelled'}:
            return None
        # A previous bridge may have died while its child still owns a local
        # lease. `work --once` returning idle does not mean this job finished.
        return subprocess.Popen([sys.executable, '-m', 'ascendra.execution_cli',
            '--data', str(folder), 'work', '--once', '--owner', 'sites_bridge'],
            cwd=Path(__file__).resolve().parent.parent, env=worker_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)

    def progress(self, local_id):
        queue, _, _ = self.jobs[local_id]
        job = queue.get(local_id)
        return {'state': job['state'], 'completed_steps': sorted(job['checkpoints']),
                'provider': 'ollama', 'model': self.model}

    def finished(self, local_id):
        return self.jobs[local_id][0].get(local_id)['state'] in {'completed', 'failed', 'cancelled'}

    def cancel(self, local_id):
        self.jobs[local_id][0].cancel(local_id, 'sites_bridge')

    def result(self, local_id):
        queue, folder, remote = self.jobs[local_id]
        job = queue.get(local_id)
        if job['state'] not in {'completed', 'failed', 'cancelled'}:
            raise RuntimeError('Local executor has not finished')
        result = job.get('result') or {'status': job['state']}
        verified = result.get('status') == 'verified'
        attempts = result.get('attempts', [])
        report = next((a['verification'] for a in reversed(attempts)
                       if isinstance(a.get('verification'), dict)), {'passed': False, 'checks': []})
        output = {'status': 'completed' if verified else 'failed', 'result': {
            'local_status': result.get('status'), 'reason': result.get('reason'),
            'report': report, 'verification_level': remote['snapshot'].get('verification_level', 'smoke'),
            'verification_contract_sha256': remote['snapshot'].get('verification_contract_sha256'),
            'provider': 'ollama', 'model': self.model, 'published': False}}
        if remote['snapshot'].get('verification_contract') is not None and (
                job['payload'].get('contract') != remote['snapshot']['verification_contract']):
            raise ValueError('Local test contract does not match approved snapshot')
        if verified:
            if report.get('passed') is not True:
                raise ValueError('Verified result lacks passing evidence')
            output['result']['files'] = bounded_artifact(result['artifact'], folder)
            verified_attempt = next((a for a in reversed(attempts) if a.get('status') == 'verified'), {})
            output['result']['artifact_sha256'] = {}
            for file in output['result']['files']:
                digest = hashlib.sha256(file['content'].encode()).hexdigest()
                if verified_attempt.get('files', {}).get(file['path']) != digest:
                    raise ValueError('Artifact changed since verification')
                output['result']['artifact_sha256'][file['path']] = digest
        if 'budget' in str(result.get('reason', '')):
            output['status'] = 'budget_exhausted'
        if len(json.dumps(output, ensure_ascii=False).encode()) > 690000:
            raise ValueError('Result and evidence too large')
        return output

    def prepare_followup(self, remote):
        from .continuation_worker import schedule_after_run
        key = hashlib.sha256(remote['id'].encode()).hexdigest()
        folder = self.data / key
        if any(p.is_symlink() for p in (folder, *folder.parents)) or not (folder / 'execution.sqlite3').exists():
            raise ValueError('Verified parent storage unavailable')
        parent_id = (remote.get('checkpoint') or {}).get('local_id')
        if not parent_id or remote['snapshot'].get('followup_research') is not True:
            raise ValueError('Followup was not explicitly enabled')
        parent = ExecutionQueue(folder / 'execution.sqlite3').get(parent_id, owner_id='sites_bridge')
        queue = ExecutionQueue(folder / 'continuation.sqlite3')
        topic = ('Research three evidence-based improvements after this completed project: ' +
                 parent['payload']['description'])[:4000]
        child = schedule_after_run(queue, parent, topic, enabled=True)
        self.followups[child['id']] = (queue, folder)
        return child['id']

    def start_followup(self, local_id):
        queue, folder = self.followups[local_id]
        if queue.get(local_id)['state'] in {'completed', 'failed', 'cancelled'}:
            return None
        return subprocess.Popen([sys.executable, '-m', 'ascendra.continuation_worker',
            '--data', str(folder), '--once', '--model', self.model, '--owner', 'sites_bridge'],
            cwd=Path(__file__).resolve().parent.parent, env=worker_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)

    def followup_result(self, local_id):
        job = self.followups[local_id][0].get(local_id)
        result = job.get('result') or {}
        if job['state'] == 'completed' and result.get('status') == 'awaiting_selection':
            return {'status': 'completed', 'batch': result['batch'], 'child_id': local_id}
        return {'status': 'failed', 'child_id': local_id}

    def followup_finished(self, local_id):
        return self.followups[local_id][0].get(local_id)['state'] in {'completed', 'failed', 'cancelled'}

    def cancel_followup(self, local_id):
        self.followups[local_id][0].cancel(local_id, 'sites_bridge')


def main():
    line = sys.stdin.readline(65537)
    if len(line) > 65536:
        raise ValueError('Configuration too large')
    config = json.loads(line)
    transport = SitesTransport(config['site'], config['service_token'], config['bridge_token'])
    runner = LocalRunner(config['data'], config.get('model', 'qwen2.5-coder:7b'))
    lock_path = runner.data / '.bridge.lock'
    if lock_path.is_symlink():
        raise ValueError('Symlink worker lock forbidden')
    lock = lock_path.open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.time() + 86400
    # Stable nonsecret identity permits recovering a still-live followup lease
    # after restart. Never run two bridge processes for the same data directory.
    worker_id = 'worker_' + hashlib.sha256(str(runner.data).encode()).hexdigest()[:40]
    bridge = ExecutionBridge(transport, runner, worker_id=worker_id,
                             stopping=lambda: stopping or time.time() >= deadline)
    print('Execution bridge: local Ollama worker; credentials remain in memory.', flush=True)
    while not bridge.stopping():
        try:
            # Followups have their own explicit budget and lease, and never
            # delay publication of the parent application's result.
            followup = bridge.run_followup_once()
            if followup != 'idle':
                print('Followup research state: ' + followup, flush=True)
            state = bridge.run_once()
            if state != 'idle':
                print('Execution completed with state: ' + state, flush=True)
        except Exception:
            print('Execution bridge paused after transport or worker failure; no details exposed.', flush=True)
        for _ in range(20):
            if bridge.stopping():
                break
            time.sleep(.25)


if __name__ == '__main__':
    main()
