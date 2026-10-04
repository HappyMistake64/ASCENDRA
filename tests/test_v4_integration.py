"""Synthetic orchestration tests: no provider network or benchmark case access."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascendra import method_research_v4 as v4
from ascendra.v4_ledger import FileLedger
from ascendra.v4_grading import validate_private_grade, evaluate_v4, OUTPUT_LIMIT_BYTES
from ascendra.subscription import ProviderBlocked
from ascendra.v4_protocol import (PROTOCOL, QUALITY_GATE, SELECTION_RULE,
                                  freeze_manifest, make_schedule, manifest_hash,
                                  evaluate_gates)


class FakeProvider:
    def __init__(self, tokens=11):
        self.call_records = []
        self.requests = []
        self.tokens = tokens

    def _exec(self, request, schema):
        self.requests.append(json.loads(request))
        self.call_records.append(dict(status='completed', tool_calls=0,
                                      total_tokens=self.tokens))
        return {'content': 'print(7)'}


def grading(*, solved=True, status='pass'):
    return dict(solved=solved, passed=int(solved), executed=1, total=1,
                duration_s=.01, results=[dict(passed=solved, status=status)])


class V4IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.study = v4.where(self.root)
        folder = self.study/'tasks'/'synthetic'
        (folder/'.ascendra_hidden').mkdir(parents=True)
        self.task = dict(task_id='synthetic', statement='Print seven',
                         examples=[{'input': '', 'output': '7'}])
        self.bundle = dict(bundle_sha256='b'*64)
        for name, value in [('public.json', self.task), ('bundle.json', self.bundle),
                            ('.ascendra_hidden/cases.json', [{'input': 'PRIVATE_SENTINEL', 'output': '7'}])]:
            (folder/name).write_text(json.dumps(value))
        entry = dict(id='synthetic', difficulty='easy', bundle_sha256='b'*64,
                     public_sha256=v4.digest((folder/'public.json').read_bytes()),
                     bundle_file_sha256=v4.digest((folder/'bundle.json').read_bytes()),
                     private_sha256=v4.digest((folder/'.ascendra_hidden/cases.json').read_bytes()))
        self.manifest = dict(protocol=PROTOCOL, experiment_id=v4.STUDY, pilot=True,
                             model='fake', reasoning='low', backend_revision=None,
                             git_commit='fixture', worktree_diff_sha256='d'*64,
                             data_version='fixture', checks_version='fixture',
                             seed=1, prompts={'base': 'fixture'}, limits={'budgets': v4.BUDGETS},
                             environment={'test': True}, selection_rule=SELECTION_RULE,
                             gates=dict(QUALITY_GATE), previous_task_ids=[], source_files={},
                             tasks={'development': [entry], 'confirmation': []})
        self.spec = next(s for s in make_schedule(self.manifest, 'development')
                         if s['method'] == 'adaptive_repair')
        self.ledger = FileLedger(self.study/'ledger', manifest_hash(self.manifest), v4.BUDGETS)
        self.provider = FakeProvider()
        self.out = self.study/'trials'/'development'/'synthetic__adaptive_repair__r0'

    @staticmethod
    def public_controller(task, method, call, bundle):
        code = call(1, {'task_id': task['task_id'], 'public_examples': task['examples']})
        return code, dict(status='evaluated', selected_index=0,
                          program_hashes=[v4.digest(code.encode())],
                          public_scores=[dict(solved=True, passed=1, total=1)],
                          bundle_sha256=bundle['bundle_sha256'], diagnostic_error=None)

    def trial(self):
        return v4.run_trial(self.root, self.manifest, self.spec, self.ledger, self.provider)

    def test_selection_is_frozen_before_private_access_and_result_cache_prevents_calls(self):
        original_load = v4.load
        accesses = []
        def inspect_load(path):
            if Path(path).name == 'cases.json':
                self.assertTrue((self.out/'selection.json').exists())
                accesses.append(path)
            return original_load(path)
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', return_value=grading()), patch.object(v4, 'load', side_effect=inspect_load):
            first = self.trial()
            second = self.trial()
        self.assertEqual(first, second)
        self.assertEqual(len(accesses), 1)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(self.provider.requests))
        self.assertEqual(self.ledger.summary()['calls'], 1)

    def test_resume_after_grader_interruption_does_not_reinvoke_model(self):
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', side_effect=RuntimeError('synthetic grader crash')):
            with self.assertRaises(RuntimeError):
                self.trial()
        self.assertTrue((self.out/'selection.json').exists())
        self.assertFalse((self.out/'result.json').exists())
        with patch.object(v4, 'controller', side_effect=AssertionError('selection already frozen')), patch.object(v4, 'evaluate', return_value=grading()):
            self.assertTrue(self.trial()['solved'])
        self.assertEqual(len(self.provider.requests), 1)

    def test_unknown_usage_is_preserved_and_deployment_gate_fails_closed(self):
        self.provider.tokens = None
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', return_value=grading()):
            result = self.trial()
        self.assertIsNone(result['total_tokens'])
        self.assertEqual(self.ledger.summary()['unknown_usage_calls'], 1)
        # Supply the other complete registered arm; neither development nor unknown
        # accounting may accidentally produce an affirmative deployment verdict.
        other = next(s for s in make_schedule(self.manifest, 'development') if s['method'] == 'best_of_two')
        other = dict(result, **other)
        report = evaluate_gates(self.manifest, 'development', [result, other], 0)
        self.assertFalse(report['token_deployment_pass'])
        self.assertFalse(report['promotion_allowed'])

    def test_dependency_tamper_is_rejected_before_trial(self):
        dependency = self.root/'frozen_dependency.py'
        dependency.write_text('VERSION = 1\n')
        self.manifest['source_files'] = {'frozen_dependency.py': v4.digest(dependency.read_bytes())}
        freeze_manifest(self.manifest, self.study/'manifest.json')
        with patch.object(v4, 'verify_bundle', return_value=True):
            self.assertEqual(v4.verify(self.root), self.manifest)
            dependency.write_text('VERSION = 2\n')
            with self.assertRaisesRegex(ValueError, 'Frozen source changed'):
                v4.verify(self.root)
        self.assertEqual(len(self.provider.requests), 0)

    def test_invalid_private_grading_cannot_be_recorded_as_valid(self):
        invalid = grading(solved=False, status='suite_timeout')
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', return_value=invalid):
            with self.assertRaises(ValueError):
                self.trial()
        self.assertFalse((self.out/'result.json').exists())

    def test_cached_selection_cannot_be_reused_under_changed_manifest(self):
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):
                self.trial()
        self.manifest['prompts']['base'] = 'different'
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', return_value=grading()) as grader:
            with self.assertRaises(ValueError):
                self.trial()
            grader.assert_not_called()

    def test_cached_result_must_match_requested_spec(self):
        with patch.object(v4, 'controller', self.public_controller), patch.object(v4, 'evaluate', return_value=grading()):
            self.trial()
        self.spec = dict(self.spec, order=self.spec['order']+10)
        with self.assertRaises(ValueError):
            self.trial()


class PrivateGradingTests(unittest.TestCase):
    def test_program_failures_are_valid_but_suite_failures_are_not(self):
        for status in ('wrong_answer', 'runtime_error', 'timeout'):
            value = grading(solved=False, status=status)
            value['total'] = 4  # Valid early exit after the first program failure.
            self.assertIs(validate_private_grade(value, 4), value)
        for status in ('suite_timeout', 'grader_error', 'unknown'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_private_grade(grading(solved=False, status=status), 1)

    def test_inconsistent_or_missing_grading_is_invalid(self):
        changes = [('solved', 1), ('solved', False), ('passed', 0),
                   ('executed', True), ('total', 2), ('duration_s', float('nan')),
                   ('duration_s', -1), ('results', [])]
        for key, value in changes:
            malformed = grading()
            malformed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_private_grade(malformed, 1)
        with self.assertRaises(ValueError):
            validate_private_grade({'solved': True}, 1)
        with self.assertRaises(ValueError):
            validate_private_grade(grading(), 0)

    def test_passing_prefix_is_not_a_complete_suite(self):
        prefix = grading()
        prefix.update(total=3, solved=False)
        with self.assertRaisesRegex(ValueError, 'truncated'):
            validate_private_grade(prefix, 3)


class V4EvaluatorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bwrap'), 'OS sandbox requires bwrap')
    def test_legal_two_megabyte_output_passes_actual_sandbox(self):
        size = 2 * 1024 * 1024
        result = evaluate_v4(f"print('x' * {size})", [{'input': '', 'output': 'x' * size}])
        self.assertTrue(result['solved'])
        validate_private_grade(result, 1)
        self.assertEqual(set(result['results'][0]), {'passed', 'status', 'returncode'})

    @unittest.skipUnless(shutil.which('bwrap'), 'OS sandbox requires bwrap')
    def test_program_exceeding_four_megabytes_is_rejected_actual_sandbox(self):
        result = evaluate_v4(f"print('x' * {OUTPUT_LIMIT_BYTES + 100})", [{'input': '', 'output': 'short'}])
        self.assertFalse(result['solved'])
        self.assertEqual(result['results'][0]['status'], 'runtime_error')
        validate_private_grade(result, 1)

    def test_isolation_failure_is_not_a_program_failure(self):
        def isolation_failed(command, **kwargs):
            kwargs['stderr'].write(b'bwrap: namespace setup failed')
            return subprocess.CompletedProcess(command, 1)
        with patch('subprocess.run', side_effect=isolation_failed):
            with self.assertRaises(ProviderBlocked):
                evaluate_v4('print(7)', [{'input': '', 'output': '7'}])

    def test_suite_budget_timeout_is_invalid_evidence(self):
        with patch('time.monotonic', side_effect=[0, 179, 181]), patch('subprocess.run', side_effect=subprocess.TimeoutExpired('sandbox', 1)):
            result = evaluate_v4('print(7)', [{'input': '', 'output': '7'}])
        self.assertEqual(result['results'][0]['status'], 'suite_timeout')
        with self.assertRaises(ValueError):
            validate_private_grade(result, 1)

    def test_case_timeout_is_valid_program_failure(self):
        with patch('time.monotonic', side_effect=[0, 1, 10]), patch('subprocess.run', side_effect=subprocess.TimeoutExpired('sandbox', 8)):
            result = evaluate_v4('print(7)', [{'input': '', 'output': '7'}])
        self.assertEqual(result['results'][0]['status'], 'timeout')
        validate_private_grade(result, 1)


if __name__ == '__main__':
    unittest.main()
