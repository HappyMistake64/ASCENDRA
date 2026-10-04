"""Publish a bounded autonomous-run dashboard snapshot to one authenticated Site.

The only remote control is a stop request bound to the posted run identifier.
Credentials are accepted through the environment or one JSON line on stdin.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request

from .capability_memory import ExperienceStore

MAX_BYTES = 1024 * 1024
TERMINAL = {'completed', 'stopped', 'failed', 'finished', 'budget_exhausted', 'deadline'}
_ROUND = re.compile(r'round-\d{3,6}$')
_WORKER = re.compile(r'worker-\d{2,4}$')
_HASH = re.compile(r'[a-f0-9]{64}$')


def _text(value, limit=1000, token=''):
    if not isinstance(value, str):
        return ''
    if token:
        value = value.replace(token, '[redacted]')
    value = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [redacted]', value)
    value = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)', '[redacted]', value)
    value = re.sub(r'(?i)\b((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', value)
    value = re.sub(r'(?<![\w:])/(?:[^\s"\'<>\[\]()]+)', '[path]', value)
    value = re.sub(r'\b[A-Za-z]:\\[^\s"\']+', '[path]', value)
    return ''.join(char for char in value if char in '\n\t' or ord(char) >= 32)[:limit]


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _path(root, relative):
    path = root / relative
    if path != root and root not in path.parents:
        raise ValueError('Invalid run-relative path')
    current = root
    for part in path.relative_to(root).parts:
        if part in ('.', '..'):
            raise ValueError('Invalid run-relative path')
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink run metadata is not supported')
    return path


def _read(root, relative, *, optional=True, tail=False):
    path = _path(root, relative)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if optional:
            return ''
        raise ValueError('Required run metadata is missing') from None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Run metadata must be a regular unlinked file')
        offset = max(0, info.st_size-MAX_BYTES) if tail else 0
        if info.st_size > MAX_BYTES and not tail:
            raise ValueError('Run metadata exceeds the size limit')
        stream.seek(offset)
        data = stream.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError('Run metadata exceeds the size limit')
        if offset:
            data = data.partition(b'\n')[2]
        return data.decode('utf-8')


def _json(root, relative, *, optional=True):
    raw = _read(root, relative, optional=optional)
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise ValueError('Run metadata must be an object')
    return value


def authorized_run(output):
    root = Path(output).resolve(strict=True)
    if not root.is_dir() or _json(root, 'configuration.json', optional=False).get('mode') != 'autonomous':
        raise ValueError('Output is not an autonomous run')
    return root


def _task(value, token):
    value = value if isinstance(value, dict) else {}
    return {key: _text(value.get(key), 1200 if key == 'goal' else 200, token)
            for key in ('title', 'goal')}


def snapshot(root, *, token=''):
    """Export allowlisted display fields, never raw prompts, logs or host paths."""
    config = _json(root, 'configuration.json', optional=False)
    current = _json(root, 'status.json')
    run_id = root.name
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', run_id):
        run_id = 'run-' + hashlib.sha256(run_id.encode()).hexdigest()[:24]
    status = {key: _number(current.get(key)) for key in
              ('round', 'max_agents', 'max_calls', 'reserved_calls', 'completed_tasks',
               'started_at', 'deadline_at', 'updated_at')}
    status.update(state=_text(current.get('state', 'starting'), 80, token),
                  mission=_text(current.get('mission', config.get('mission')), 4000, token))
    usage = current.get('usage', {})
    status['usage'] = {key: _number(usage.get(key)) for key in
                       ('calls', 'known_tokens', 'unknown_usage_calls')}
    agents = []
    for agent in current.get('agents', [])[:50]:
        progress = agent.get('progress', {})
        agents.append(dict(id=_text(agent.get('id'), 80, token),
            state=_text(agent.get('state'), 80, token), task=_task(agent.get('task'), token),
            call_limit=_number(agent.get('call_limit')),
            progress={**{key: _text(progress.get(key), 100, token) for key in ('state', 'action', 'tool')},
                      **{key: _number(progress.get(key)) for key in ('step', 'updated_at')}}))
    events = []
    for line in _read(root, 'events.jsonl', tail=True).splitlines(keepends=True):
        if not line.endswith('\n'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        item = {key: _text(event[key], 1200, token) for key in
                ('event', 'state', 'agent', 'id', 'rationale', 'message') if key in event}
        item.update({key: _number(event[key]) for key in
                     ('at', 'round', 'capacity', 'reserved_calls', 'completed_tasks') if key in event})
        if 'task' in event:
            item['task'] = _task(event['task'], token)
        if 'tasks' in event:
            item['tasks'] = [_task(task, token) for task in event['tasks'][:50]]
        events.append(item)
    rounds, changes = [], []
    directories = sorted(path for path in root.iterdir() if _ROUND.fullmatch(path.name))[-50:]
    for directory in directories:
        _path(root, directory.name)
        plan = _json(root, directory.name+'/plan.json')
        if plan:
            rounds.append(dict(round=int(directory.name.split('-')[1]),
                rationale=_text(plan.get('rationale'), 1200, token),
                tasks=[_task(task, token) for task in plan.get('tasks', [])[:50]]))
        for worker in sorted(directory.iterdir()):
            if not _WORKER.fullmatch(worker.name):
                continue
            result = _json(root, directory.name+'/'+worker.name+'/result.json')
            for change in result.get('changes', [])[:64]:
                relative = change.get('path', '')
                if not isinstance(relative, str) or relative.startswith(('/', '\\')) or '..' in relative.split('/'):
                    continue
                changes.append(dict(agent='r'+str(int(directory.name.split('-')[1]))+'-w'+str(int(worker.name.split('-')[1])),
                    path=_text(relative, 300, token),
                    **{key: change.get(key) if isinstance(change.get(key), str) and _HASH.fullmatch(change[key]) else None
                       for key in ('before_sha256', 'after_sha256')}))
    capabilities = []
    raw = _read(root, 'memory/experience.json')
    if raw:
        # Reuse the trusted journal/hash-chain validator on an immutable read-only
        # snapshot. Avoid ExperienceStore.__init__, which initializes absent memory.
        store = object.__new__(ExperienceStore)
        store.path = SimpleNamespace(read_text=lambda: raw)
        for value in list(store._capabilities(store._read()).values())[-100:]:
            capabilities.append(dict(id=_text(value['id'], 100, token),
                name=_text(value['spec'].get('name'), 200, token),
                status=_text(value['status'], 80, token),
                description=_text(value['spec'].get('description'), 1000, token)))
    result = dict(run_id=run_id, observed_at=time.time(), status=status, agents=agents,
        events=events[-50:], rounds=rounds, capabilities=capabilities, changes=changes[-200:],
        limits={key: _number(config.get(key)) for key in ('max_agents', 'max_calls', 'max_steps', 'minutes')})
    # Bound by encoded bytes, not character count (Czech and other Unicode count).
    while len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
        candidates = [key for key in ('rounds', 'events', 'changes', 'capabilities') if result[key]]
        if not candidates:
            raise ValueError('Dashboard snapshot exceeds the size limit')
        largest = max(candidates, key=lambda key: len(json.dumps(result[key]).encode()))
        result[largest].pop(0)
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Telemetry redirects are forbidden')


def endpoint(origin):
    parsed = urllib.parse.urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Site origin must be an HTTPS origin without credentials or a path')
    return origin.rstrip('/')+'/api/ingest'


def post(origin, token, payload):
    request = urllib.request.Request(endpoint(origin), data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json', 'OAI-Sites-Authorization': 'Bearer '+token}, method='POST')
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Oversized telemetry response')
    reply = json.loads(raw)
    if not isinstance(reply, dict) or type(reply.get('stop_requested')) is not bool:
        raise ValueError('Invalid telemetry response')
    return reply


def request_stop(root):
    path = _path(root, 'STOP')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid STOP marker')
        return
    with os.fdopen(fd, 'w') as stream:
        stream.write('Stop requested through the authenticated dashboard.\n')


def _health(root, value):
    target = _path(root, 'bridge_status.json')
    fd, name = tempfile.mkstemp(prefix='.bridge-', dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def bridge(root, origin, token, *, once=False):
    endpoint(origin)
    if not isinstance(token, str) or not token or len(token) > 16384 or any(c.isspace() for c in token):
        raise ValueError('Missing or invalid Sites service credential')
    health = dict(pid=os.getpid(), started_at=time.time(), last_success_at=None, failures=0)
    while True:
        try:
            payload = snapshot(root, token=token)
            reply = post(origin, token, payload)
            if reply.get('run_id') != payload['run_id']:
                raise ValueError('Telemetry acknowledgement does not match this run')
            if reply['stop_requested']:
                request_stop(root)
            health.update(last_success_at=time.time(), error=None, failures=0,
                          stop_requested=reply['stop_requested'], run_id=payload['run_id'])
            terminal = payload['status']['state'] in TERMINAL
        except Exception as exc:
            # Never serialize exception messages: HTTP/proxy errors can contain credentials.
            health.update(error=type(exc).__name__, failures=health['failures']+1)
            terminal = False
        health['updated_at'] = time.time()
        _health(root, health)
        if once or terminal:
            return 0 if health.get('error') is None else 1
        time.sleep(5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--site-origin', required=True)
    parser.add_argument('--token-stdin', action='store_true', help='Read one JSON line containing token from stdin')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    try:
        root = authorized_run(args.output)
        token = os.environ.pop('ASCENDRA_SITES_TOKEN', '')
        if args.token_stdin:
            line = sys.stdin.readline(20000)
            if len(line) >= 20000:
                raise ValueError('Credential input is too large')
            token = json.loads(line)['token']
        return bridge(root, args.site_origin, token, once=args.once)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print('Telemetry bridge failed: '+type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
