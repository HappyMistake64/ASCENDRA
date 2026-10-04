import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ascendra import hard_controller, hard_validators as validators, v4_controller


class HardBundleIntegrityTests(unittest.TestCase):
    def setUp(self):
        validators._registered_payload.cache_clear()
        self.addCleanup(validators._registered_payload.cache_clear)
        self.task = {'task_id': 'abc392_g', 'statement': 'Public synthetic fixture.',
                     'examples': [{'input': '1\n', 'output': '2\n', 'private': 'SECRET'}],
                     'private_cases': 'SECRET'}
        self.payload = {'cases': [{'input': '1\n', 'output': '2\n', 'label': 'example'}],
                        'validation_evidence': {'reference': 'unit-test fixture'}}
        self.module = SimpleNamespace(
            build_cases=lambda task: copy.deepcopy(self.payload),
            verify_cases=lambda task, cases: cases == self.payload['cases'])
        patcher = patch.object(validators, '_module', return_value=self.module)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rehash(self, bundle):
        bundle['bundle_sha256'] = validators._digest({k: v for k, v in bundle.items()
                                                     if k != 'bundle_sha256'})

    def test_public_only_snapshot_deterministic_and_independent_of_callers(self):
        first = validators.build_bundle(self.task)
        self.assertNotIn('SECRET', json.dumps(first))
        self.assertEqual(first, validators.build_bundle(self.task))
        first['cases'][0]['input'] = 'changed'
        self.assertEqual(validators.build_bundle(self.task)['cases'][0]['input'], '1\n')

    def test_changed_and_rehashed_cases_or_evidence_are_rejected(self):
        for field, value in [('output', 'wrong'), ('input', '2'), ('label', 'renamed')]:
            with self.subTest(field=field):
                bundle = validators.build_bundle(self.task)
                bundle['cases'][0][field] = value
                self.rehash(bundle)
                with self.assertRaises(ValueError): validators.verify_bundle(bundle)
        bundle = validators.build_bundle(self.task)
        bundle['validation_evidence']['reference'] = 'fabricated'
        self.rehash(bundle)
        with self.assertRaises(ValueError): validators.verify_bundle(bundle)

    def test_task_mismatch_and_extra_public_snapshot_fields_are_rejected(self):
        bundle = validators.build_bundle(self.task)
        with self.assertRaises(ValueError): validators.verify_bundle(bundle, 'abc399_f')
        bundle['public_task']['private'] = 'SECRET'
        self.rehash(bundle)
        with self.assertRaises(ValueError): validators.verify_bundle(bundle)

    def test_invalid_case_counts_and_output_capacity_fail_before_model_calls(self):
        for count in (0, validators.MAX_CASES+1):
            validators._registered_payload.cache_clear()
            self.payload['cases'] = [{'input': '1', 'output': '1', 'label': str(i)}
                                     for i in range(count)]
            with self.assertRaises(ValueError): validators.build_bundle(self.task)
        validators._registered_payload.cache_clear()
        self.payload['cases'] = [{'input': '1', 'output': 'x' * (validators.MAX_OUTPUT_BYTES+1),
                                 'label': 'too-large'}]
        with self.assertRaises(ValueError): validators.build_bundle(self.task)

    def test_oracle_verifier_is_mandatory(self):
        self.module.verify_cases = lambda task, cases: False
        with self.assertRaises(ValueError): validators.build_bundle(self.task)

    def test_controller_logic_and_prompts_identical_to_frozen_v4(self):
        self.assertEqual(inspect.getsource(hard_controller.controller),
                         inspect.getsource(v4_controller.controller))
        self.assertEqual(hard_controller.BASE, v4_controller.BASE)
        self.assertEqual(hard_controller.REPAIR, v4_controller.REPAIR)
        self.assertIs(hard_controller.verify_bundle, validators.verify_bundle)

    def test_bad_bundle_fails_closed_without_any_model_call(self):
        bundle = validators.build_bundle(self.task)
        bundle['cases'][0]['output'] = 'wrong'
        self.rehash(bundle)
        calls = []
        result, selected = hard_controller.controller(
            self.task, 'adaptive_repair', lambda *args: calls.append(args), bundle)
        self.assertIsNone(result)
        self.assertEqual(selected['status'], 'unevaluated')
        self.assertEqual(calls, [])

    def test_public_case_label_survives_omitted_large_input_feedback(self):
        self.payload['cases'] = [{'input': '1 ' * 30000, 'output': '2\n',
                                 'label': 'large-all-equal-values'}]
        bundle = validators.build_bundle(self.task)
        requests = []
        def call(stage, request):
            requests.append(request)
            return 'print(2)'
        def grader(code, cases, **kwargs):
            return {'solved': False, 'passed': 0, 'total': 1, 'executed': 1,
                    'duration_s': 0.1, 'private_metadata': 'SECRET',
                    'results': [{'passed': False, 'status': 'wrong_answer',
                                 'private_metadata': 'SECRET', 'label': 'UNTRUSTED'}]}
        _, selected = hard_controller.controller(self.task, 'adaptive_repair', call,
                                                  bundle, grader=grader)
        feedback = requests[1]['public_feedback']
        case = feedback['results'][0]
        self.assertEqual(case['label'], 'large-all-equal-values')
        self.assertNotIn('input', case)
        self.assertEqual(case['input_omitted']['characters'], 60000)
        self.assertNotIn('SECRET', json.dumps(requests))
        self.assertNotIn('UNTRUSTED', json.dumps(feedback))
        self.assertLessEqual(len(json.dumps(feedback, sort_keys=True)), 20000)
        self.assertEqual(selected['status'], 'evaluated')


class HardBundleIntegrationTests(unittest.TestCase):
    def test_all_twelve_real_public_contracts_and_cases_validate(self):
        fixtures = Path(__file__).parent / 'fixtures' / 'hard_public_tasks.json'
        tasks = json.loads(fixtures.read_text())
        self.assertEqual({t['task_id'] for t in tasks}, set(validators.SUPPORTED_TASKS))
        for task in tasks:
            with self.subTest(task=task['task_id']):
                bundle = validators.build_bundle(task)
                self.assertTrue(validators.verify_bundle(bundle, task['task_id']))
                self.assertLessEqual(len(bundle['cases']), validators.MAX_CASES)
                self.assertEqual(bundle['public_task']['statement'], task['statement'])
                # Every public sample must be included; metadata does not enter checks.
                for example in task['examples']:
                    self.assertTrue(any(c['input'].split() == example['input'].split() and
                                        c['output'].split() == example['output'].split()
                                        for c in bundle['cases']))


if __name__ == '__main__':
    unittest.main()
