"""Public-only hard-development policy controller; callers persist selection before grading holdout.

All controls have equal, fixed weight. The bundle validation authority is the
bundle builder/verifier; this module additionally checks its admission schema.
"""
from copy import deepcopy
import math
import re
import json

from .method_research_v3 import BASE, sha
from .v4_grading import evaluate_v4 as evaluate
from .hard_validators import verify_bundle

METHODS = ('best_of_two', 'adaptive_repair')
REPAIR = (BASE + ' Repair the previous program using only the verified public '
          'test feedback. Correct the reported failures and preserve correct behavior. '
          'Feedback includes at most 8 failed cases and 20000 JSON characters. '
          'Large inputs or expected outputs may be omitted and identified only by '
          'SHA256 and character count; omitted data is not an executable testcase.')
FEEDBACK_MAX_CASES = 8
FEEDBACK_MAX_CHARS = 20000


class DiagnosticError(ValueError):
    """A result cannot safely drive selection or model feedback."""


def _cases(value, *, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise DiagnosticError('Missing public cases')
    if any(not isinstance(c, dict) or
           any(not isinstance(c.get(k), str) for k in ('input', 'output'))
           for c in value):
        raise DiagnosticError('Invalid public case')
    clean = []
    for case in value:
        item = {'input': case['input'], 'output': case['output']}
        if 'label' in case:
            if not isinstance(case['label'], str):
                raise DiagnosticError('Invalid public case label')
            item['label'] = case['label'][:160]
        clean.append(item)
    return clean


def _score(value, cases):
    """Validate V3 totals and statuses; never forward arbitrary grader fields."""
    if not isinstance(value, dict):
        raise DiagnosticError('Invalid diagnostic result')
    results = value.get('results')
    n = len(cases)
    if not isinstance(results, list) or len(results) != n:
        raise DiagnosticError('Incomplete diagnostic results')
    clean = []
    for result, case in zip(results, cases):
        if not isinstance(result, dict):
            raise DiagnosticError('Invalid case result')
        status = result.get('status')
        if status not in ('pass', 'wrong_answer', 'runtime_error', 'timeout'):
            raise DiagnosticError('Unrecognized diagnostic status')
        if type(result.get('passed')) is not bool or result['passed'] != (status == 'pass'):
            raise DiagnosticError('Inconsistent case result')
        item = {'passed': result['passed'], 'status': status,
                'input': case['input'], 'expected': case['output']}
        if 'label' in case:
            item['label'] = case['label']
        for key, limit in (('actual', 3000), ('stderr', 1500)):
            if key in result:
                if not isinstance(result[key], str):
                    raise DiagnosticError('Invalid diagnostic text')
                item[key] = result[key][:limit]
        clean.append(item)
    passed = sum(r['passed'] for r in clean)
    for key, expected in (('passed', passed), ('executed', n), ('total', n)):
        if type(value.get(key)) is not int or value[key] != expected:
            raise DiagnosticError('Inconsistent diagnostic totals')
    if type(value.get('solved')) is not bool or value['solved'] != (passed == n):
        raise DiagnosticError('Inconsistent solved flag')
    duration = value.get('duration_s')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise DiagnosticError('Invalid diagnostic duration')
    return {'solved': passed == n, 'passed': passed, 'executed': n, 'total': n,
            'duration_s': duration, 'results': clean}


def _diagnose(code, cases, grader, rechecks, program_index):
    score = _score(grader(code, deepcopy(cases), public=True), cases)
    for index, result in enumerate(score['results']):
        # V3 reports CPU-limit kills as runtime_error without a return code.
        # Repeat those as well as wall timeouts rather than overlooking CPU limits.
        if result['status'] in ('timeout', 'runtime_error'):
            case = [cases[index]]
            repeated = _score(grader(code, deepcopy(case), public=True), case)
            rechecks.append({'program_index': program_index, 'case_index': index,
                             'evaluation': repeated})
            if repeated['results'][0]['status'] != result['status']:
                raise DiagnosticError('Nonreproducible execution failure')
    return score


def repair_feedback(score):
    """Bound model exposure deterministically without pretending fragments are cases."""
    feedback = {key: score[key] for key in ('solved', 'passed', 'total')}
    failures = [r for r in score['results'] if not r['passed']]
    feedback.update(results=[], omitted_failures=len(failures))
    for result in failures[:FEEDBACK_MAX_CASES]:
        item = deepcopy(result)
        for key in ('actual', 'stderr'):
            if key in item:
                item[key] = item[key][:1000]
        proposed = {**feedback, 'results': feedback['results'] + [item],
                    'omitted_failures': feedback['omitted_failures'] - 1}
        if len(json.dumps(proposed, sort_keys=True)) > FEEDBACK_MAX_CHARS:
            for key in ('input', 'expected'):
                value = item.pop(key)
                item[key + '_omitted'] = {'sha256': sha(value.encode()), 'characters': len(value)}
            proposed['results'] = feedback['results'] + [item]
        if len(json.dumps(proposed, sort_keys=True)) > FEEDBACK_MAX_CHARS:
            break
        feedback = proposed
    return feedback


def controller(task, method, call, bundle, grader=evaluate):
    """Return (code, selection), or (None, unevaluated) on diagnostic failure.

    call(stage, request) is invoked at most twice. Provider exceptions propagate
    to the accounting/recovery layer; diagnostic exceptions fail closed here.
    No task fields other than task_id, statement and examples enter requests.
    """
    if method not in METHODS:
        raise ValueError('Unknown method')
    selection = {'status': 'unevaluated', 'method': method, 'selected_index': None,
                 'public_scores': [], 'program_hashes': [], 'call_count': 0,
                 'bundle_sha256': None, 'timeout_rechecks': [],
                 'diagnostic_error': None}
    try:
        if not isinstance(bundle, dict) or bundle.get('validated') is not True:
            raise DiagnosticError('Unvalidated public bundle')
        digest = bundle.get('bundle_sha256')
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise DiagnosticError('Invalid bundle fingerprint')
        selection['bundle_sha256'] = digest
        try:
            verified = verify_bundle(bundle, task_id=task.get('task_id'))
        except ValueError as exc:
            raise DiagnosticError('Public bundle verification failed') from exc
        if verified is not True:
            raise DiagnosticError('Public bundle verification failed')
        cases = _cases(bundle.get('cases'))
        examples = _cases(task.get('examples'), allow_empty=True)
        if any(not isinstance(task.get(k), str) for k in ('task_id', 'statement')):
            raise DiagnosticError('Invalid public task')
        if bundle.get('statement_sha256') != sha(task['statement'].encode()):
            raise DiagnosticError('Public bundle statement mismatch')
        public_task = {k: task[k] for k in ('task_id', 'statement')}
    except (DiagnosticError, AttributeError) as exc:
        selection['diagnostic_error'] = str(exc) if isinstance(exc, DiagnosticError) else 'Invalid public task'
        return None, selection

    def request(instruction):
        return {'instruction': instruction, 'task_id': public_task['task_id'],
                'public_files': {'problem.txt': public_task['statement']},
                'public_examples': deepcopy(examples)}

    programs = []
    for stage in (1, 2):
        req = request(BASE)
        if stage == 2 and method == 'adaptive_repair':
            if selection['public_scores'][0]['solved']:
                break
            req = request(REPAIR)
            req.update(previous_program=programs[0],
                       public_feedback=repair_feedback(selection['public_scores'][0]))
        code = call(stage, req)
        if not isinstance(code, str) or not code.strip() or len(code) > 100000:
            raise ValueError('Invalid candidate program')
        programs.append(code)
        selection['call_count'] += 1
        selection['program_hashes'].append(sha(code.encode()))
        try:
            score = _diagnose(code, cases, grader, selection['timeout_rechecks'], stage - 1)
        except Exception as exc:
            # Infrastructure errors are never treated as candidate failures, and
            # exception text from arbitrary graders is never sent to a model.
            selection['diagnostic_error'] = (str(exc) if isinstance(exc, DiagnosticError)
                                             else 'Grader failed: ' + type(exc).__name__)
            return None, selection
        selection['public_scores'].append(score)
    chosen = max(range(len(programs)), key=lambda i: selection['public_scores'][i]['passed'])
    selection.update(status='evaluated', selected_index=chosen)
    return programs[chosen], selection
