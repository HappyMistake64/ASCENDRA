"""Local durable executor for static web applications with independent browser tests.

Usage: python -m ascendra.execution_cli --data PATH enqueue --owner USER --key KEY
       --description TEXT --contract checks.json
       python -m ascendra.execution_cli --data PATH work [--once]

Run on a dedicated trusted workspace/container, not a machine with browser sessions
or unrelated secrets. Generated JavaScript runs in an isolated browser profile;
browser checks require Linux namespace isolation; continuous hosting is not provisioned.
Only installed local Ollama models are supported. Work has no deployment side effects.
A reserved model call without a saved candidate after a crash fails as uncertain;
it is never silently replayed. Completed candidate/test checkpoints can resume.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from .execution_queue import ExecutionQueue, LeaseLost
from .browser_sandbox import build_command
from .project_planner import planning_schema, planning_prompt, validate_plan_response
from .local_llm import DEFAULT_MODEL, LocalDecider
from .project_workflow import Step, WorkflowLimits, run_plan, run_project_workflow
from .studio_projects import ALLOWED_FILES, build_project
from .studio_store import _json

BROWSER = Path(__file__).with_name('browser_verify.mjs').resolve()
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class StopRequested(RuntimeError):
    pass


class UncertainModelCall(RuntimeError):
    pass


def _read_json(path, maximum=1024 * 1024):
    with Path(path).open('rb') as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError('JSON file too large')
    return json.loads(value)


def _write_json(path, value):
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    # Output paths belong to this trusted executor, never to generated code.
    with path.open('x', encoding='utf-8') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def fingerprint(path):
    path = Path(path)
    if not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Missing or unsafe artifact')
    hashes, size = {}, 0
    for file in sorted(path.rglob('*')):
        if file.is_symlink():
            raise ValueError('Symlink artifact')
        if file.is_file():
            size += file.stat().st_size
            if size > 4 * 1024 * 1024 or len(hashes) >= 100:
                raise ValueError('Artifact too large')
            hashes[str(file.relative_to(path))] = hashlib.sha256(file.read_bytes()).hexdigest()
        elif not file.is_dir():
            raise ValueError('Invalid artifact file')
    if 'index.html' not in hashes:
        raise ValueError('Missing index.html')
    return hashes


def _terminate(process):
    # Kill the complete session, including Chromium children. Sending to a dead
    # process group is harmless; never signal an unrelated process's group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_process(argv, *, timeout_s, log_path, pulse):
    """Trusted host subprocess; pulse checks cancellation/lease every 250 ms."""
    pulse()
    env = dict(os.environ)
    env['PYTHONPATH'] = str(PACKAGE_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    with Path(log_path).open('xb') as output:
        process = subprocess.Popen(argv, cwd=PACKAGE_ROOT, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        try:
            while True:
                pulse()
                code = process.poll()
                if code is not None:
                    return code
                if time.monotonic() - started >= timeout_s:
                    raise TimeoutError('Subprocess time budget exhausted')
                if output.tell() > 2 * 1024 * 1024:
                    raise ValueError('Subprocess output limit exceeded')
                time.sleep(.25)
        finally:
            _terminate(process)


def validate_contract(contract):
    """Use the same trusted declarative validator as the browser runner."""
    encoded = _json(contract)
    if len(encoded.encode()) > 128 * 1024:
        raise ValueError('Contract too large')
    script = ("import {validateContract} from " + json.dumps(BROWSER.as_uri()) + ";"
              "let s=''; for await(const c of process.stdin)s+=c; validateContract(JSON.parse(s));")
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=encoded,
                            text=True, capture_output=True, timeout=10, cwd=PACKAGE_ROOT)
    if result.returncode:
        raise ValueError('Invalid independent browser contract')
    return contract


def worker_limit(requested):
    value = int(os.environ.get('ASCENDRA_MAX_WORKERS', '2'))
    if not 1 <= value <= 50:
        raise ValueError('ASCENDRA_MAX_WORKERS must be 1..50')
    return min(requested, value)


def enqueue(queue, *, owner, key, description, contract, max_calls=4,
            max_repairs=3, max_seconds=1800, model=DEFAULT_MODEL,
            ollama_url='http://127.0.0.1:11434', max_tokens=None, max_agents=1, strategy='sequential'):
    if not isinstance(description, str) or not description.strip() or len(description.encode()) > 8000:
        raise ValueError('Description must contain 1..8000 bytes')
    if type(max_seconds) not in (float, int) or not math.isfinite(max_seconds):
        raise ValueError('Invalid time limit')
    limits = WorkflowLimits(max_repairs=max_repairs, max_model_calls=max_calls, max_seconds=max_seconds)
    if type(max_agents) is not int or not 1 <= max_agents <= 50:
        raise ValueError('max_agents must be 1..50')
    if max_tokens is None:
        max_tokens = max_calls * 20480
    if type(max_tokens) is not int or max_tokens < 20480:
        raise ValueError('max_tokens must admit at least one 20480-token reservation')
    effective_calls = min(max_calls, max_tokens // 20480)
    if strategy not in ('sequential', 'planned'):
        raise ValueError('Unknown execution strategy')
    if strategy == 'planned' and effective_calls < 2:
        raise ValueError('Planned strategy needs one planner and at least one builder call')
    validate_contract(contract)
    return queue.enqueue(owner, key, {'description': description, 'contract': contract, 'strategy': strategy,
        'limits': {'max_repairs': limits.max_repairs, 'max_model_calls': effective_calls,
                   'max_seconds': limits.max_seconds},
        'budget': {'max_tokens': max_tokens, 'reserved_tokens_per_call': 20480,
                   'max_agents': max_agents, 'requested_model_calls': max_calls},
        'provider': {'model': model, 'endpoint': ollama_url}})


def execute_claim(queue, job, data, *, stop=None, process_runner=run_process):
    """Execute a claimed job. Test injection is trusted host code, never model input."""
    stop = stop or threading.Event()
    data = Path(data).absolute()
    if any(p.is_symlink() for p in (data, *data.parents)):
        raise ValueError('Symlink execution root forbidden')
    job_root = data / 'runs' / job['id']
    fence_root = job_root / ('fence-%d' % job['fence'])
    fence_root.mkdir(parents=True, exist_ok=False)
    worker, fence, identifier = job['worker_id'], job['fence'], job['id']
    payload = job['payload']
    points = dict(job['checkpoints'])
    last_heartbeat = 0.
    failure = None
    checkpoint_lock = threading.RLock()

    def save(step, result):
        nonlocal points
        with checkpoint_lock:
            updated = queue.checkpoint(identifier, worker, fence, step, result)
            points = updated['checkpoints']
            return result

    def pulse():
        nonlocal last_heartbeat
        if stop.is_set():
            raise StopRequested('Worker stopping')
        current = queue.get(identifier)
        if (current['state'] != 'running' or current['worker_id'] != worker or current['fence'] != fence):
            raise LeaseLost('Job cancelled or reassigned')
        if time.monotonic() - last_heartbeat >= 1:
            queue.heartbeat(identifier, worker, fence, lease_seconds=60)
            last_heartbeat = time.monotonic()
        if 'started' in points and time.time() >= points['started']['deadline']:
            raise TimeoutError('Persistent job time budget exhausted')

    def run(argv, log_name, *, cap=900):
        pulse()
        timeout = min(cap, points['started']['deadline'] - time.time())
        return process_runner(argv, timeout_s=timeout, log_path=fence_root / log_name, pulse=pulse)

    def reserve(key, details):
        with checkpoint_lock:
            if key in points:
                raise UncertainModelCall('Reserved inference has no committed output; refusing replay')
            if sum(item.startswith('call-') for item in points) >= payload['limits']['max_model_calls']:
                raise ValueError('Persistent model-call budget exhausted')
            return save(key, {'reserved_at': time.time(), **details})

    def planned_generate(description, path):
        capacity = min(worker_limit(payload['budget']['max_agents']),
                       payload['limits']['max_model_calls'] - 1)
        if 'planning' in points:
            plan = validate_plan_response(points['planning']['response'], points['planning']['capacity'])
        else:
            request = {'description': description, 'contract': payload['contract'],
                       'provider': payload['provider'], 'max_calls': 1, 'capacity': capacity}
            request_path = fence_root / 'planning-request.json'
            output_path = fence_root / 'planning-response.json'
            _write_json(request_path, request)
            reserve('call-planner', {'role': 'planner'})
            code = run([sys.executable, '-m', 'ascendra.execution_cli', '_plan',
                        '--request', str(request_path), '--destination', str(output_path),
                        '--ledger', str(job_root / 'provider' / 'planner')], 'planner.log')
            if code:
                raise RuntimeError('Model planner failed')
            response = _read_json(output_path)
            plan = validate_plan_response(response, capacity)
            pulse()
            save('planning', {'response': response, 'capacity': capacity})
        reports = {}
        by_id = {item['id']: item for item in plan}

        def build_candidate(step, output_dir, dependencies):
            pulse()
            item = by_id[step.id]
            key = 'builder-' + step.id
            candidate = output_dir / 'candidate-000'
            if key in points:
                original = Path(points[key]['path'])
                if fingerprint(original) != points[key]['files']:
                    raise ValueError('Saved builder artifact hash mismatch')
                shutil.copytree(original, candidate)
            else:
                request = {'description': description, 'contract': payload['contract'],
                           'provider': payload['provider'], 'max_calls': 1,
                           'approach': item['approach']}
                request_path = fence_root / (key + '-request.json')
                _write_json(request_path, request)
                reserve('call-' + key, {'role': 'builder', 'worker': step.id})
                code = run([sys.executable, '-m', 'ascendra.execution_cli', '_generate',
                            '--request', str(request_path), '--destination', str(candidate),
                            '--ledger', str(job_root / 'provider' / key)], key + '.log')
                if code:
                    raise RuntimeError('Builder model failed')
                pulse()
                save(key, {'path': str(candidate), 'files': fingerprint(candidate)})
            report = verify(candidate, verification_key=key, concurrent_workers=1)
            reports[step.id] = {'candidate': candidate, 'report': report}
            _write_json(output_dir / 'worker-result.json', {'id': step.id, 'passed': report['passed']})

        dispatch = run_plan([Step(item['id']) for item in plan], fence_root / 'builders',
            execute=build_candidate, max_agents=capacity,
            cancelled=lambda: stop.is_set() or queue.get(identifier)['state'] != 'running')
        # A failed sibling does not erase independently verified output. If none
        # generated an inspectable candidate, never substitute a template.
        ready = [item['id'] for item in plan if item['id'] in reports]
        if not ready:
            raise RuntimeError('All planned builders failed: ' + json.dumps(dispatch['errors']))
        selected = next((key for key in ready if reports[key]['report']['passed']), ready[0])
        chosen = reports[selected]
        shutil.copytree(chosen['candidate'], path)
        hashes = fingerprint(path)
        save('generated-000', {'path': str(path), 'files': hashes})
        save('tested-000', {'files': hashes, 'report': chosen['report']})
        save('planning-result', {'selected': selected, 'workers': dispatch['steps'],
            'errors': dispatch['errors'], 'requested_workers': payload['budget']['max_agents'],
            'effective_workers': min(capacity, len(plan))})

    def generate(description, path, previous=None, verification=None):
        nonlocal failure
        try:
            pulse()
            attempt = int(path.name.rsplit('-', 1)[1])
            key = 'generated-%03d' % attempt
            reserved = 'call-%03d' % attempt
            if key in points:
                source = Path(points[key]['path'])
                if fingerprint(source) != points[key]['files']:
                    raise ValueError('Saved candidate hash mismatch')
                shutil.copytree(source, path)
                return
            request = {'description': description, 'contract': payload['contract'],
                       'provider': payload['provider'], 'max_calls': payload['limits']['max_model_calls']}
            if previous is not None:
                request['repair'] = {'files': {name: (previous / name).read_text()
                    for name in ALLOWED_FILES if (previous / name).is_file()}, 'verification': verification}
            request_path = fence_root / ('request-%03d.json' % attempt)
            _write_json(request_path, request)
            reserve(reserved, {'attempt': attempt, 'role': 'repair' if previous else 'builder'})
            code = run([sys.executable, '-m', 'ascendra.execution_cli', '_generate',
                        '--request', str(request_path), '--destination', str(path),
                        '--ledger', str(job_root / 'provider')], 'model-%03d.log' % attempt)
            if code:
                raise RuntimeError('Model generation failed; inspect model log')
            pulse()
            save(key, {'path': str(path), 'files': fingerprint(path)})
        except Exception as exc:
            failure = type(exc).__name__
            raise

    def verify(path, *, verification_key=None, concurrent_workers=None):
        nonlocal failure
        try:
            pulse()
            attempt = int(path.name.rsplit('-', 1)[1])
            key = 'tested-' + verification_key if verification_key else 'tested-%03d' % attempt
            hashes = fingerprint(path)
            if key in points:
                if points[key]['files'] != hashes:
                    raise ValueError('Saved verification hash mismatch')
                return points[key]['report']
            reports = {}
            scenarios = payload['contract']['scenarios']

            def check_scenario(step, output_dir, dependencies):
                index = int(step.id.split('-')[1])
                checkpoint_key = key + '-%03d' % index
                if checkpoint_key in points:
                    if points[checkpoint_key]['files'] != hashes:
                        raise ValueError('Saved scenario hash mismatch')
                    report = points[checkpoint_key]['report']
                    _write_json(output_dir / 'report.json', report)
                else:
                    contract = {'version': 1, 'scenarios': [scenarios[index]]}
                    contract_path = fence_root / (key + '-contract-%03d.json' % index)
                    _write_json(contract_path, contract)
                    output = output_dir / 'report.json'
                    code = run(build_command(path, contract_path, output),
                               key + '-browser-%03d.log' % index, cap=180)
                    if code not in (0, 1):
                        raise RuntimeError('Browser verifier failed to execute')
                    report = _read_json(output)
                    for number, check in enumerate(report.get('checks', [])):
                        check['name'] = '%s:%s:%s' % (check.get('scenario', scenarios[index]['name']),
                            check.get('step', number), check.get('action', 'check'))
                    if report.get('page_errors'):
                        report['checks'].append({'name': scenarios[index]['name'] + ':no_browser_errors', 'passed': False})
                    report['screenshots'] = [str(output_dir / shot.removeprefix('/output/'))
                        for shot in report.get('screenshots', []) if shot.startswith('/output/')]
                    if type(report.get('passed')) is not bool or not report.get('checks') or any(
                        type(c.get('passed')) is not bool for c in report['checks']
                    ) or report['passed'] != all(c['passed'] for c in report['checks']):
                        raise ValueError('Invalid browser verification evidence')
                    pulse()
                    save(checkpoint_key, {'files': hashes, 'report': report})
                reports[index] = report

            plan = run_plan([Step('scenario-%03d' % i) for i in range(len(scenarios))],
                fence_root / (key + '-workers'), execute=check_scenario,
                max_agents=concurrent_workers or worker_limit(payload.get('budget', {}).get('max_agents', 1)),
                cancelled=lambda: stop.is_set() or queue.get(identifier)['state'] != 'running')
            if plan['status'] != 'completed':
                raise RuntimeError('Independent browser worker failed: ' + json.dumps(plan['errors']))
            report = {'passed': all(r['passed'] for r in reports.values()),
                      'checks': [check for i in sorted(reports) for check in reports[i]['checks']],
                      'page_errors': [error for i in sorted(reports) for error in reports[i].get('page_errors', [])],
                      'screenshots': [shot for i in sorted(reports) for shot in reports[i].get('screenshots', [])],
                      'verification_workers': len(scenarios),
                      'requested_workers': payload.get('budget', {}).get('max_agents', 1),
                      'max_concurrent_workers': min(len(scenarios), concurrent_workers or worker_limit(payload.get('budget', {}).get('max_agents', 1)))}
            if fingerprint(path) != hashes:
                raise ValueError('Verifier changed generated files')
            pulse()
            save(key, {'files': hashes, 'report': report})
            return report
        except Exception as exc:
            failure = type(exc).__name__
            raise

    try:
        pulse()
        validate_contract(payload['contract'])
        if 'started' not in points:
            save('started', {'at': time.time(), 'deadline': time.time() + payload['limits']['max_seconds']})
        _write_json(fence_root / 'contract.json', payload['contract'])
        if payload.get('strategy') == 'planned' and 'generated-000' not in points:
            planned_generate(payload['description'], fence_root / 'planned-selected')
        remaining = points['started']['deadline'] - time.time()
        if remaining <= 0:
            raise TimeoutError('Persistent job time budget exhausted')
        limits = WorkflowLimits(**{**payload['limits'], 'max_seconds': remaining})
        result = run_project_workflow(payload['description'], fence_root / 'workflow',
            generate=generate, verify=verify,
            repair=lambda description, previous, report, path: generate(description, path, previous, report),
            limits=limits, cancelled=lambda: stop.is_set() or queue.get(identifier)['state'] == 'cancelled')
        result['generation_rounds'] = result['model_calls']
        result['model_calls'] = sum(key.startswith('call-') for key in points)
        result['model_call_accounting'] = 'reserved_upper_bound_including_uncertain_calls'
        result['reserved_tokens'] = result['model_calls'] * 20480
        if 'planning-result' in points:
            result['planning'] = points['planning-result']
        if failure:
            result['error_type'] = failure
        if stop.is_set():
            return {'status': 'interrupted', 'reason': 'worker_stopped', 'job_id': identifier}
        current = queue.get(identifier)
        if current['state'] == 'cancelled':
            return {'status': 'cancelled', 'job_id': identifier}
        _write_json(fence_root / 'executor-result.json', result)
        queue.finish(identifier, worker, fence,
                     state='completed' if result['status'] == 'verified' else 'failed', result=result)
        return result
    except (LeaseLost, StopRequested):
        state = queue.get(identifier)['state']
        return {'status': 'cancelled' if state == 'cancelled' else 'interrupted',
                'reason': 'lease_lost_or_worker_stopped', 'job_id': identifier}
    except Exception as exc:
        if stop.is_set():
            return {'status': 'interrupted', 'reason': 'worker_stopped', 'job_id': identifier}
        if queue.get(identifier)['state'] == 'cancelled':
            return {'status': 'cancelled', 'job_id': identifier}
        result = {'status': 'failed', 'reason': 'executor_failure', 'error_type': type(exc).__name__,
                  'published': False, 'artifact': None}
        try:
            queue.finish(identifier, worker, fence, state='failed', result=result)
        except LeaseLost:
            pass
        return result


def _generate(args):
    request = _read_json(args.request)
    decider = LocalDecider(args.ledger, max_calls=request['max_calls'], **request['provider'])
    def decide(prompt, schema):
        prompt = {**prompt, 'acceptance_contract': request['contract']}
        if 'approach' in request:
            prompt['implementation_approach'] = request['approach']
            prompt['scope'] = 'Implement the full unchanged user brief and acceptance contract; approach is subordinate to them.'
        if 'repair' in request:
            prompt.update(task='Repair the previous static web candidate using actual independent test failures.',
                          previous_candidate=request['repair']['files'],
                          verification=request['repair']['verification'])
        return decider(prompt, schema)
    build_project(request['description'], Path(args.destination), decide=decide)
    return 0


def _plan(args):
    request = _read_json(args.request)
    decider = LocalDecider(args.ledger, max_calls=1, **request['provider'])
    response = decider(planning_prompt(request['description'], request['contract'], request['capacity']),
                       planning_schema(request['capacity']))
    validate_plan_response(response, request['capacity'])
    _write_json(args.destination, response)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('enqueue')
    add.add_argument('--owner', required=True)
    add.add_argument('--key', required=True)
    add.add_argument('--description', required=True)
    add.add_argument('--contract', type=Path, required=True)
    add.add_argument('--max-calls', type=int, default=4)
    add.add_argument('--max-repairs', type=int, default=3)
    add.add_argument('--max-tokens', type=int)
    add.add_argument('--max-agents', type=int, default=1)
    add.add_argument('--strategy', choices=('sequential', 'planned'), default='sequential')
    add.add_argument('--max-seconds', type=float, default=1800)
    add.add_argument('--model', default=DEFAULT_MODEL)
    add.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    status = commands.add_parser('status')
    status.add_argument('--owner')
    cancel = commands.add_parser('cancel')
    cancel.add_argument('job_id')
    cancel.add_argument('--owner', required=True)
    work = commands.add_parser('work')
    work.add_argument('--once', action='store_true')
    work.add_argument('--owner')
    for command in ('_generate', '_plan'):
        internal = commands.add_parser(command, help=argparse.SUPPRESS)
        for name in ('request', 'destination', 'ledger'):
            internal.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    if args.command in ('_generate', '_plan'):
        return _generate(args) if args.command == '_generate' else _plan(args)
    if args.data is None:
        parser.error('--data is required')
    data = args.data.absolute()
    if any(p.is_symlink() for p in (data, *data.parents)):
        parser.error('Symlink data path forbidden')
    queue = ExecutionQueue(data / 'execution.sqlite3')
    if args.command == 'enqueue':
        result = enqueue(queue, owner=args.owner, key=args.key, description=args.description,
            contract=_read_json(args.contract, 128 * 1024), max_calls=args.max_calls,
            max_repairs=args.max_repairs, max_seconds=args.max_seconds,
            model=args.model, ollama_url=args.ollama_url, max_tokens=args.max_tokens, max_agents=args.max_agents, strategy=args.strategy)
    elif args.command == 'status':
        result = queue.list_jobs(owner_id=args.owner)
    elif args.command == 'cancel':
        result = queue.cancel(args.job_id, args.owner)
    else:
        stop = threading.Event()
        old_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
        worker = 'worker-' + uuid.uuid4().hex
        try:
            while not stop.is_set():
                job = queue.claim(worker, owner_id=args.owner)
                result = execute_claim(queue, job, data, stop=stop) if job else {'status': 'idle'}
                if job or args.once:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.once:
                    return 0 if result['status'] in ('verified', 'idle') else 1
                stop.wait(1 if job else 2)
            return 0
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
