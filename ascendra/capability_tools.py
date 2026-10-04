"""Bounded project tools for capability experiments; no benchmark data access.

The test tool runs standard-library unittest with the system Python, on a fresh
filtered, read-only project snapshot. It does not install dependencies or accept
shell commands. Writes require an explicit exact-path allowlist.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time

MAX_FILE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_FILES = 1000
MAX_OUTPUT_BYTES = 128 * 1024
_PRIVATE = {'.ascendra_hidden', '.ascendra', '.git', '.ssh', '.aws', '.azure',
            '.config', '.codex', '.netrc', '.npmrc', '.pypirc', '.docker', '.kube',
            '.credentials', 'credentials', 'secrets', 'node_modules',
            '__pycache__', '.venv', 'venv'}


def _blocked(name):
    name = name.casefold()
    return (name in _PRIVATE or name.startswith(('.env', 'auth', '.auth', '.ascendra'))
            or name.startswith(('credentials.', 'secrets.', 'id_rsa', 'id_ed25519'))
            or name.endswith(('.pem', '.key')))


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


_STR = {'type': 'string'}
_DESCRIPTORS = [
    {'name': 'list_files', 'description': 'List accessible public project files; private paths and symlinks are excluded.',
     'input_schema': _schema({'path': _STR})},
    {'name': 'read_file', 'description': 'Read a UTF-8 public file, with a SHA256 and bounded content.',
     'input_schema': _schema({'path': _STR}, ('path',))},
    {'name': 'search_text', 'description': 'Search literal text in public UTF-8 files. Results and line lengths are bounded.',
     'input_schema': _schema({'query': _STR, 'path': _STR}, ('query',))},
    {'name': 'run_tests', 'description': 'Discover unittest tests using system Python in a network-disabled, read-only project sandbox. Failed tests are valid results; zero tests are not successful.',
     'input_schema': _schema({'start_dir': _STR, 'pattern': _STR})},
    {'name': 'write_file', 'description': 'Atomically replace an explicitly writable public path. Optional expected_sha256 checks the existing content before replacement.',
     'input_schema': _schema({'path': _STR, 'content': _STR, 'expected_sha256': _STR}, ('path', 'content'))},
]

_TEST_RUNNER = r'''
import contextlib, io, json, resource, sys, unittest
resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))
resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
sys.dont_write_bytecode = True
sys.path.insert(0, '/project')
class BoundedOutput(io.TextIOBase):
    def __init__(self): self.parts=[]; self.remaining=32768; self.truncated=False
    def write(self, value):
        value=str(value)
        if len(value)>self.remaining: self.truncated=True
        if self.remaining and value: self.parts.append(value[:self.remaining])
        self.remaining=max(0,self.remaining-len(value))
        return len(value)
    def flush(self): pass
    def getvalue(self): return ''.join(self.parts)
output=BoundedOutput()
with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
    suite=unittest.defaultTestLoader.discover(start_dir=sys.argv[1], pattern=sys.argv[2])
    result=unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
print(json.dumps(dict(tests_run=result.testsRun, failures=len(result.failures),
    errors=len(result.errors), successful=result.testsRun>0 and result.wasSuccessful(),
    output=output.getvalue(), output_truncated=output.truncated)))
'''


class ToolCatalog:
    def __init__(self, project_root, writable_paths=None):
        self.root = Path(project_root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Project root must be a directory')
        self._lock = threading.RLock()
        self.writable_paths = frozenset('/'.join(self._parts(p)) for p in (writable_paths or ()))

    def descriptors(self):
        return json.loads(json.dumps(_DESCRIPTORS))

    def _parts(self, path, *, allow_root=False):
        if not isinstance(path, str) or not path or len(path) > 1024 or '\\' in path or '\x00' in path:
            raise ValueError('Invalid relative project path')
        if path == '.' and allow_root:
            return ()
        raw = path.split('/')
        if (PurePosixPath(path).is_absolute() or any(p in ('', '.', '..') for p in raw)
                or any(_blocked(p) for p in raw)):
            raise ValueError('Path is outside the permitted public project scope')
        return tuple(raw)

    @contextmanager
    def _directory(self, parts):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def _read_bytes(self, parts):
        with self._directory(parts[:-1]) as directory:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Only regular, unlinked public files are accessible')
                if info.st_size > MAX_FILE_BYTES:
                    raise ValueError('Public file exceeds the 1 MiB tool limit')
                with os.fdopen(fd, 'rb', closefd=False) as stream:
                    raw = stream.read(MAX_FILE_BYTES+1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError('Public file exceeds the 1 MiB tool limit')
                return raw
            finally:
                os.close(fd)

    def _files(self, parts=()):
        """Walk without following symlinks or leaking names of excluded paths."""
        count = directories = 0
        def walk(prefix):
            nonlocal count, directories
            directories += 1
            if directories > MAX_FILES or len(prefix) > 32:
                raise ValueError('Public project directory traversal exceeds the tool limit')
            with self._directory(prefix) as directory:
                with os.scandir(directory) as entries:
                    names = []
                    for entry in entries:
                        names.append(entry.name)
                        if len(names) > 10000:
                            raise ValueError('Public directory exceeds the entry limit')
                    names.sort()
                for name in names:
                    if _blocked(name):
                        continue
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    path = prefix + (name,)
                    if stat.S_ISDIR(info.st_mode):
                        yield from walk(path)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        count += 1
                        if count > MAX_FILES:
                            raise ValueError('Public project exceeds the 1000-file tool limit')
                        yield path
        yield from walk(parts)

    def _list_files(self, args):
        parts = self._parts(args.get('path', '.'), allow_root=True)
        files = ['/'.join(p) for p in self._files(parts)]
        return {'files': files[:500], 'truncated': len(files) > 500, 'total': len(files)}

    def _read_file(self, args):
        parts = self._parts(args['path'])
        raw = self._read_bytes(parts)
        content = raw.decode('utf-8')
        return {'path': '/'.join(parts), 'content': content[:65536],
                'truncated': len(content) > 65536, 'sha256': hashlib.sha256(raw).hexdigest()}

    def _search_text(self, args):
        query = args['query']
        if not query or len(query) > 512:
            raise ValueError('Search query must contain 1..512 characters')
        parts = self._parts(args.get('path', '.'), allow_root=True)
        if parts:
            with self._directory(parts[:-1]) as directory:
                info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            paths = [parts] if stat.S_ISREG(info.st_mode) else self._files(parts)
        else:
            paths = self._files()
        matches = []
        total_bytes = 0
        for path in paths:
            try:
                raw = self._read_bytes(path)
                total_bytes += len(raw)
                if total_bytes > MAX_SNAPSHOT_BYTES:
                    raise ValueError('Search exceeds the 16 MiB aggregate read limit')
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if query in line:
                    if len(matches) == 100:
                        return {'matches': matches, 'truncated': True}
                    matches.append({'path': '/'.join(path), 'line': number, 'text': line[:400]})
        return {'matches': matches, 'truncated': False}

    def _write_file(self, args):
        parts = self._parts(args['path'])
        if '/'.join(parts) not in self.writable_paths:
            raise ValueError('Path is not explicitly writable')
        raw = args['content'].encode('utf-8')
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('Write exceeds the 1 MiB tool limit')
        expected = args.get('expected_sha256')
        if expected is not None and (len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('Expected SHA256 must be a lowercase 64-character digest')
        with self._directory(parts[:-1]) as directory:
            mode = 0o644
            try:
                info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Write target must be a regular file, never a link')
                mode = stat.S_IMODE(info.st_mode) & 0o777
                previous = self._read_bytes(parts)
            except FileNotFoundError:
                previous = None
            if expected is not None and (previous is None or hashlib.sha256(previous).hexdigest() != expected):
                raise ValueError('Expected SHA256 does not match existing file')
            temporary = '.capability-write-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, parts[-1], src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return {'path': '/'.join(parts), 'bytes_written': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def _snapshot(self, destination):
        total = 0
        for parts in self._files():
            raw = self._read_bytes(parts)
            total += len(raw)
            if total > MAX_SNAPSHOT_BYTES:
                raise ValueError('Public snapshot exceeds the 16 MiB tool limit')
            path = destination.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def _run_tests(self, args):
        start = args.get('start_dir', 'tests')
        self._parts(start, allow_root=True)
        pattern = args.get('pattern', 'test*.py')
        if not pattern or len(pattern) > 128 or '/' in pattern or '\\' in pattern or '\x00' in pattern:
            raise ValueError('Test pattern must be a filename glob, not a command or path')
        bwrap = shutil.which('bwrap')
        if not bwrap:
            raise RuntimeError('Required bwrap sandbox is unavailable')
        with tempfile.TemporaryDirectory(prefix='ascendra-capability-') as td:
            base = Path(td)
            project = base / 'project'
            project.mkdir()
            self._snapshot(project)
            if not (project / start).is_dir():
                raise ValueError('Test start directory is not an accessible public directory')
            runner = base / 'runner.py'
            runner.write_text(_TEST_RUNNER)
            command = [bwrap, '--die-with-parent', '--unshare-all', '--cap-drop', 'ALL']
            for path in ('/usr', '/lib', '/lib64', '/bin'):
                if Path(path).exists():
                    command += ['--ro-bind', path, path]
            command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                        '--ro-bind', str(project), '/project', '--ro-bind', str(runner), '/runner.py',
                        '--chdir', '/project', '--', '/usr/bin/python3', '-I', '-B', '/runner.py', start, pattern]
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=20,
                                           env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
                out.seek(0); raw = out.read(MAX_OUTPUT_BYTES+1)
                err.seek(0); errors = err.read(4096).decode('utf-8', errors='replace')
            if completed.returncode != 0:
                raise RuntimeError('Sandbox test runner failed (exit ' + str(completed.returncode) + '): ' + errors[-1500:])
            if len(raw) > MAX_OUTPUT_BYTES:
                raise RuntimeError('Test runner exceeded its output limit')
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise RuntimeError('Test runner returned an invalid summary') from exc
            if (not isinstance(result, dict) or
                any(type(result.get(k)) is not int or result[k] < 0 for k in ('tests_run', 'failures', 'errors')) or
                type(result.get('successful')) is not bool or not isinstance(result.get('output'), str) or
                result['successful'] != (result['tests_run'] > 0 and result['failures'] == 0 and result['errors'] == 0)):
                raise RuntimeError('Test runner returned an invalid summary')
            return result

    def execute(self, name, args):
        started = time.monotonic()
        result = {'status': 'error', 'tool': name, 'data': None, 'error': None, 'duration_s': 0.0}
        try:
            descriptors = {d['name']: d for d in _DESCRIPTORS}
            if not isinstance(name, str) or name not in descriptors:
                raise ValueError('Unknown project tool')
            schema = descriptors[name]['input_schema']
            if (not isinstance(args, dict) or set(args) - set(schema['properties']) or
                not set(schema['required']) <= set(args) or any(not isinstance(v, str) for v in args.values())):
                raise ValueError('Arguments do not match the tool input schema')
            with self._lock:
                result['data'] = getattr(self, '_' + name)(args)
            result['status'] = 'ok'
        except subprocess.TimeoutExpired:
            result['error'] = 'Sandbox test runner exceeded the 20-second wall limit'
        except Exception as exc:
            # Paths in OSError text could disclose excluded host names. Report
            # generic filesystem failures, while retaining our own bounded errors.
            result['error'] = str(exc)[:2000] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        result['duration_s'] = time.monotonic()-started
        return result
