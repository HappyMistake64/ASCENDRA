import copy
import json
import unittest
from unittest.mock import patch

from ascendra import v4_controller as v4
from ascendra.v4_validators import build_bundle


def score(statuses):
    results = [{'status': s, 'passed': s == 'pass'} for s in statuses]
    return {'results': results, 'passed': sum(r['passed'] for r in results),
            'executed': len(results), 'total': len(results),
            'solved': all(r['passed'] for r in results), 'duration_s': 0.01}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.task = {'task_id': 'public-task', 'statement': 'Read a number.',
                     'examples': [{'input': '1', 'output': '1', 'private': 'SECRET'}],
                     'private_cases': 'SECRET'}
        self.bundle = {'validated': True, 'bundle_sha256': 'a' * 64,
                       'statement_sha256': v4.sha(self.task['statement'].encode()),
                       'cases': [{'input': '1', 'output': '1'},
                                 {'input': '2', 'output': '2'}]}
        # These policy tests isolate the independently tested validator layer.
        self.verifier = patch.object(v4, 'verify_bundle', return_value=True)
        self.verifier.start()
        self.addCleanup(self.verifier.stop)
        self.calls = []

    def call(self, stage, request):
        self.calls.append((stage, copy.deepcopy(request)))
        return f'program{stage}'

    def run_policy(self, method, scores):
        supplied = iter(scores)
        return v4.controller(self.task, method, self.call, self.bundle,
                             grader=lambda *a, **kw: next(supplied))

    def test_first_prompt_identical_and_baseline_independent(self):
        self.run_policy('adaptive_repair', [score(['pass', 'pass'])])
        first = self.calls[0][1]
        self.calls.clear()
        code, selected = self.run_policy('best_of_two', [score(['pass', 'pass'])] * 2)
        self.assertEqual([c[1] for c in self.calls], [first, first])
        self.assertNotIn('SECRET', str(self.calls))
        self.assertEqual(code, 'program1')
        self.assertEqual(selected['program_hashes'], [v4.sha(b'program1'), v4.sha(b'program2')])
        self.assertEqual(selected['selected_index'], 0)

    def test_pass_stops_adaptive_at_one_call(self):
        code, selected = self.run_policy('adaptive_repair', [score(['pass', 'pass'])])
        self.assertEqual(code, 'program1')
        self.assertEqual(selected['status'], 'evaluated')
        self.assertEqual(selected['call_count'], 1)

    def test_verified_failure_repairs_and_selects_better_program(self):
        bad = score(['pass', 'wrong_answer'])
        bad['private'] = 'SECRET'
        code, selected = self.run_policy('adaptive_repair', [bad, score(['pass', 'pass'])])
        self.assertEqual(code, 'program2')
        self.assertEqual(selected['selected_index'], 1)
        repair = self.calls[1][1]
        self.assertEqual(repair['previous_program'], 'program1')
        self.assertEqual(repair['public_feedback']['results'][0]['input'], '2')
        self.assertNotIn('SECRET', str(repair))

    def test_failed_repair_keeps_first_on_tie_or_regression(self):
        for second in (['pass', 'wrong_answer'], ['wrong_answer', 'wrong_answer']):
            with self.subTest(second=second):
                code, selected = self.run_policy('adaptive_repair',
                    [score(['pass', 'wrong_answer']), score(second)])
                self.assertEqual(code, 'program1')
                self.assertEqual(selected['selected_index'], 0)

    def test_timeout_and_cpu_runtime_failure_repeated_without_extra_model_call(self):
        for status in ('timeout', 'runtime_error'):
            with self.subTest(status=status):
                self.calls.clear()
                code, selected = self.run_policy('adaptive_repair',
                    [score(['pass', status]), score([status]), score(['pass', 'pass'])])
                self.assertEqual(code, 'program2')
                self.assertEqual(len(self.calls), 2)
                self.assertEqual(len(selected['timeout_rechecks']), 1)
                self.assertEqual(selected['timeout_rechecks'][0]['case_index'], 1)

    def test_nonreproducible_timeout_is_unevaluated_without_repair(self):
        code, selected = self.run_policy('adaptive_repair',
            [score(['pass', 'timeout']), score(['pass'])])
        self.assertIsNone(code)
        self.assertEqual(selected['status'], 'unevaluated')
        self.assertEqual(len(self.calls), 1)

    def test_malformed_diagnostics_cannot_trigger_repair(self):
        malformed = [None, {}, score(['suite_timeout']), score(['pass'])]
        inconsistent = score(['pass', 'wrong_answer'])
        inconsistent['passed'] = 2
        malformed.append(inconsistent)
        inconsistent_flag = score(['pass', 'wrong_answer'])
        inconsistent_flag['results'][1]['passed'] = True
        malformed.append(inconsistent_flag)
        infinite_time = score(['pass', 'pass'])
        infinite_time['duration_s'] = float('nan')
        malformed.append(infinite_time)
        for result in malformed:
            with self.subTest(result=result):
                self.calls.clear()
                code, selected = self.run_policy('adaptive_repair', [result])
                self.assertIsNone(code)
                self.assertIsNone(selected['selected_index'])
                self.assertEqual(len(self.calls), 1)

    def test_grader_exception_is_not_candidate_failure(self):
        def broken(*args, **kwargs):
            raise RuntimeError('SECRET')
        code, selected = v4.controller(self.task, 'adaptive_repair', self.call,
                                        self.bundle, grader=broken)
        self.assertIsNone(code)
        self.assertNotIn('SECRET', selected['diagnostic_error'])
        self.assertEqual(len(self.calls), 1)

    def test_second_diagnostic_error_cancels_entire_selection(self):
        code, selected = self.run_policy('best_of_two', [score(['pass', 'pass']), {}])
        self.assertIsNone(code)
        self.assertEqual(len(selected['program_hashes']), 2)
        self.assertEqual(selected['status'], 'unevaluated')

    def test_bad_bundle_never_calls_model(self):
        for change in ({'validated': False}, {'bundle_sha256': 'bad'}, {'cases': []},
                       {'statement_sha256': 'b' * 64}):
            with self.subTest(change=change):
                code, selected = v4.controller(self.task, 'best_of_two', self.call,
                                                {**self.bundle, **change})
                self.assertIsNone(code)
                self.assertEqual(selected['call_count'], 0)
        with patch.object(v4, 'verify_bundle', side_effect=ValueError('tampered')):
            code, selected = v4.controller(self.task, 'best_of_two', self.call, self.bundle)
            self.assertIsNone(code)
        self.assertEqual(self.calls, [])

    def test_provider_failure_propagates_without_implicit_retry(self):
        def broken(stage, request):
            self.calls.append(stage)
            raise RuntimeError('transport')
        with self.assertRaisesRegex(RuntimeError, 'transport'):
            v4.controller(self.task, 'adaptive_repair', broken, self.bundle)
        self.assertEqual(self.calls, [1])

    def test_grader_cannot_mutate_frozen_bundle_cases(self):
        def mutate(code, cases, **kwargs):
            result = score(['pass', 'pass'])
            cases[0]['output'] = 'tampered'
            return result
        _, selected = v4.controller(self.task, 'adaptive_repair', self.call,
                                     self.bundle, grader=mutate)
        self.assertEqual(self.bundle['cases'][0]['output'], '1')
        self.assertEqual(selected['public_scores'][0]['results'][0]['expected'], '1')

    def test_feedback_has_hard_size_and_case_caps_without_partial_inputs(self):
        self.bundle['cases'] = [{'input': '9 ' * 500000, 'output': '2'}] * 10
        code, selected = self.run_policy('adaptive_repair',
            [score(['wrong_answer'] * 10), score(['pass'] * 10)])
        feedback = self.calls[1][1]['public_feedback']
        self.assertLessEqual(len(json.dumps(feedback, sort_keys=True)), 20000)
        self.assertEqual(len(feedback['results']), 8)
        self.assertEqual(feedback['omitted_failures'], 2)
        self.assertNotIn('input', feedback['results'][0])
        self.assertEqual(feedback['results'][0]['input_omitted']['characters'], 1000000)
        self.assertEqual(selected['public_scores'][0]['results'][0]['input'], '9 ' * 500000)


class SandboxIntegrationTests(unittest.TestCase):
    def test_real_validated_bundle_repairs_with_v3_sandbox(self):
        task = {'task_id': 'abc397_b', 'statement': 'Restore alternating io pairs.',
                'examples': [{'input': 'oi\n', 'output': '2\n'}]}
        bundle = build_bundle(task)
        correct = ("s=input().strip()\np=0\nfor c in s:\n"
                   " if c != 'io'[p%2]: p+=1\n p+=1\n"
                   "p+=p%2\nprint(p-len(s))\n")
        calls = []
        def call(stage, request):
            calls.append(stage)
            return 'print(-1)' if stage == 1 else correct
        code, selected = v4.controller(task, 'adaptive_repair', call, bundle)
        self.assertEqual(selected['status'], 'evaluated', selected['diagnostic_error'])
        self.assertEqual(calls, [1, 2])
        self.assertEqual(code, correct)
        self.assertTrue(selected['public_scores'][1]['solved'])


if __name__ == '__main__':
    unittest.main()
