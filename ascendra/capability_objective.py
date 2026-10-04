"""Host-owned mean-function objective checks, independent of project unittest.

Only candidate inputs enter the isolated process. Expected values remain in the
host controller. Passing these five cases is bounded evidence, not a proof of
correctness for all Python inputs or a capability-promotion decision.
"""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from .capability_tools import ToolCatalog
from .method_research_v3 import sandbox_command
from .v4_grading import RUNNER_V4

CONTRACT = 'mean-function-objective-v1'
_CASES = (
    ('positive-integers', [1, 2, 3], {'kind': 'value', 'value': 2.0}),
    ('fractional-result', [1, 2], {'kind': 'value', 'value': 1.5}),
    ('negative-and-positive', [-3, 1], {'kind': 'value', 'value': -1.0}),
    ('single-zero', [0], {'kind': 'value', 'value': 0.0}),
    ('empty-input', [], {'kind': 'error', 'name': 'ValueError'}),
)
_MAX_RESPONSE_BYTES = 16384


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _driver(source):
    # Candidate source is a string literal, never interpolated as driver syntax.
    return '''import contextlib, json, math, sys
payload = json.loads(sys.stdin.read())
namespace = {"__name__": "candidate"}
with contextlib.redirect_stdout(sys.stderr):
    exec(compile(SOURCE, "candidate.py", "exec"), namespace)
    try:
        value = namespace["mean"](payload)
    except ValueError:
        observed = {"kind": "error", "name": "ValueError"}
    except Exception as error:
        observed = {"kind": "error", "name": type(error).__name__}
    else:
        if type(value) in (int, float) and math.isfinite(value):
            observed = {"kind": "value", "value": float(value)}
        else:
            observed = {"kind": "invalid_return", "name": type(value).__name__}
print(json.dumps(observed, sort_keys=True, separators=(",", ":"), allow_nan=False))
'''.replace('compile(SOURCE,', 'compile(' + repr(source) + ',')


def _matches(actual, expected):
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    if expected['kind'] == 'error':
        return actual == expected
    value = actual.get('value')
    try:
        return (actual.get('kind') == 'value' and type(value) in (int, float)
                and math.isfinite(value) and value == expected['value'])
    except OverflowError:
        return False


def verify_mean(project_root, source_path):
    """Return measured case counts and hashes; fail closed on missing output.

    source_path is a public relative file under project_root. No project tests,
    dependencies, memory, private folders, or absolute host paths enter the child.
    """
    report = {'contract_id': CONTRACT, 'success': False, 'case_count': len(_CASES),
              'passed': 0, 'failed': len(_CASES), 'results': [],
              'evidence': {'contract_sha256': _hash(CONTRACT), 'fixture_sha256': _hash(_CASES)},
              'scope': 'Five independent functional cases; no automatic capability promotion.'}
    try:
        read = ToolCatalog(project_root).execute('read_file', {'path': source_path})
        if read['status'] != 'ok' or read['data']['truncated']:
            raise ValueError('Objective source must be a complete accessible public file within the read limit')
        source = read['data']['content']
        report['evidence']['source_sha256'] = read['data']['sha256']
        with tempfile.TemporaryDirectory(prefix='ascendra-mean-objective-') as temporary:
            directory = Path(temporary)
            (directory/'main.py').write_text(_driver(source))
            (directory/'runner.py').write_text(RUNNER_V4)
            for case_id, inputs, expected in _CASES:
                actual = None
                raw = b''
                status = 'invalid_output'
                try:
                    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                        process = subprocess.run(sandbox_command(directory), input=json.dumps(inputs).encode(),
                                                 stdout=out, stderr=err, timeout=8,
                                                 env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
                        out.seek(0); raw = out.read(_MAX_RESPONSE_BYTES+1)
                        err.seek(0); errors = err.read(4096)
                    if process.returncode:
                        status = 'sandbox_error' if errors.startswith(b'bwrap:') else 'runtime_error'
                    elif len(raw) <= _MAX_RESPONSE_BYTES:
                        try:
                            actual = json.loads(raw)
                            status = 'observed'
                        except (ValueError, UnicodeDecodeError):
                            pass
                except subprocess.TimeoutExpired:
                    status = 'timeout'
                except OSError:
                    status = 'sandbox_error'
                passed = status == 'observed' and _matches(actual, expected)
                report['results'].append({'case_id': case_id, 'passed': bool(passed),
                                          'status': status, 'actual_sha256': hashlib.sha256(raw).hexdigest()})
        report['passed'] = sum(item['passed'] for item in report['results'])
        report['failed'] = report['case_count']-report['passed']
        report['success'] = len(report['results']) == report['case_count'] and report['failed'] == 0
    except (ValueError, OSError) as error:
        # Do not report arbitrary filesystem paths or candidate exception text.
        report['error'] = type(error).__name__
    report['evidence']['results_sha256'] = _hash(report['results'])
    return report
