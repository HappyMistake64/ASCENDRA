"""Validate private evaluator summaries without exposing evaluator cases."""
import math


def validate_private_grade(value, case_count):
    """Accept complete passing suites or a valid stop-on-first-failure prefix.

    Suite/evaluator infrastructure timeouts are invalid evidence. Individual
    program timeouts and runtime failures remain valid unsolved outcomes.
    """
    def require(condition, message):
        if not condition:
            raise ValueError('Invalid private grading: ' + message)
    require(type(case_count) is int and case_count > 0, 'nonempty suite required')
    require(isinstance(value, dict), 'result must be an object')
    rows = value.get('results')
    require(isinstance(rows, list) and 0 < len(rows) <= case_count, 'invalid executed cases')
    for index, row in enumerate(rows):
        require(isinstance(row, dict), 'case must be an object')
        status = row.get('status')
        require(status in ('pass', 'wrong_answer', 'runtime_error', 'timeout'), 'unrecognized case status')
        require(type(row.get('passed')) is bool and row['passed'] == (status == 'pass'), 'inconsistent case status')
        require(index == len(rows)-1 or row['passed'], 'failure before final stop-first case')
    passed = sum(row['passed'] for row in rows)
    for key, expected in (('passed', passed), ('executed', len(rows)), ('total', case_count)):
        require(type(value.get(key)) is int and value[key] == expected, 'inconsistent ' + key)
    solved = passed == case_count
    require(type(value.get('solved')) is bool and value['solved'] == solved, 'inconsistent solved flag')
    require(len(rows) == case_count or rows[-1]['passed'] is False, 'truncated passing suite')
    duration = value.get('duration_s')
    require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0, 'invalid duration')
    return value


# V4 explicitly increases stdout/file capacity to accommodate legal public
# outputs (abc392_c at N=300000 needs about 2 MB). V3 remains unchanged.
OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
CASE_CPU_SECONDS = 6
CASE_WALL_SECONDS = 8
SUITE_WALL_SECONDS = 180
MEMORY_BYTES = 512 * 1024 * 1024

RUNNER_V4 = """import resource, runpy
resource.setrlimit(resource.RLIMIT_AS, (536870912,536870912))
resource.setrlimit(resource.RLIMIT_CPU, (6,6))
resource.setrlimit(resource.RLIMIT_FSIZE, (4194304,4194304))
resource.setrlimit(resource.RLIMIT_NPROC, (32,32))
runpy.run_path('/task/main.py',run_name='__main__')
"""


def evaluate_v4(code, cases, *, public=False, stop_first=False):
    """Run in the existing OS sandbox with a separately versioned V4 runner.

    Private case inputs, expected outputs and actual outputs are never returned.
    Program failures are outcomes; isolation failure raises and halts the study.
    """
    import subprocess
    import tempfile
    import time
    from pathlib import Path
    from .method_research_v3 import sandbox_command, matches
    from .subscription import ProviderBlocked

    if not isinstance(code, str) or not code.strip():
        raise ValueError('Empty candidate program')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Empty or invalid evaluator suite')
    for case in cases:
        if not isinstance(case, dict) or any(not isinstance(case.get(k), str) for k in ('input', 'output')):
            raise ValueError('Invalid evaluator case')
        if len(case['output'].encode()) > OUTPUT_LIMIT_BYTES:
            raise ValueError('Expected output exceeds registered evaluator capacity')
    start = time.monotonic()
    results = []
    with tempfile.TemporaryDirectory(prefix='ascendra-v4-run-') as temporary:
        directory = Path(temporary)
        (directory / 'main.py').write_text(code)
        (directory / 'runner.py').write_text(RUNNER_V4)
        for case in cases:
            remaining = SUITE_WALL_SECONDS - (time.monotonic() - start)
            if remaining <= 0:
                results.append({'passed': False, 'status': 'suite_timeout'})
                break
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                actual = error = ''
                returncode = None
                try:
                    process = subprocess.run(sandbox_command(directory), input=case['input'].encode(),
                                             stdout=out, stderr=err, timeout=min(CASE_WALL_SECONDS, remaining),
                                             env={'PATH': '/usr/bin:/bin'})
                    returncode = process.returncode
                    out.seek(0)
                    raw = out.read(OUTPUT_LIMIT_BYTES + 1)
                    actual = raw.decode(errors='replace')
                    err.seek(0)
                    error = err.read(4000).decode(errors='replace')
                    if returncode and error.startswith('bwrap:'):
                        raise ProviderBlocked('Candidate OS isolation failed')
                    passed = returncode == 0 and len(raw) <= OUTPUT_LIMIT_BYTES and matches(actual, case['output'])
                    status = 'pass' if passed else ('runtime_error' if returncode else 'wrong_answer')
                except subprocess.TimeoutExpired:
                    passed = False
                    status = ('suite_timeout' if remaining < CASE_WALL_SECONDS else 'timeout')
            item = {'passed': passed, 'status': status, 'returncode': returncode}
            if public:
                item.update(input=case['input'], expected=case['output'], actual=actual[:3000], stderr=error[:1500])
            results.append(item)
            if stop_first and not passed:
                break
    return {'solved': len(results) == len(cases) and all(r['passed'] for r in results),
            'passed': sum(r['passed'] for r in results), 'executed': len(results),
            'total': len(cases), 'duration_s': time.monotonic() - start, 'results': results}
