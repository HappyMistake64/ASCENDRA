import copy
import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from ascendra.capability_memory import ExperienceStore, MemoryIntegrityError, capability_sha256


def _append_from_process(directory, number):
    ExperienceStore(directory).record_episode({'objective': str(number), 'objective_success': None,
        'tool_observations': [{'tool': 'read_file', 'execution_success': True}]})


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperienceStore(self.temp.name)
        self.spec = dict(name='Diagnose tests', description='Run tests and inspect failures',
                         motivation='Avoid guessing', steps=[{'tool': 'run_tests', 'arguments': {}}],
                         success_criteria=['Explain failed assertions'], contract_id='python_test_diagnosis')

    def evidence(self, cap_id, passed=True):
        return dict(status='verified' if passed else 'failed', contract_id='python_test_diagnosis',
                    verifier_version='test-v1', capability_sha256=self.store.get_capability(cap_id)['capability_sha256'],
                    fixture_count=1, fixtures=[dict(id='fixture-a', input_sha256='a'*64, expected_sha256='b'*64)],
                    results=[dict(fixture_id='fixture-a', passed=passed, actual_sha256='c'*64)])

    def test_unknown_objective_not_failure_and_execution_not_objective(self):
        ep = self.store.record_episode(dict(objective='Fix bug', objective_success=True,
            tool_observations=[dict(tool='run_tests', execution_success=True, objective_success=True,
                                    result={'failed': 2, 'assertion': 'expected 4 got 5'})]))
        context = self.store.context()
        self.assertEqual((context['objective_success'], context['objective_pending']), (0, 1))
        self.assertEqual(context['tools']['run_tests']['execution_success'], 1)
        self.assertEqual(context['tools']['run_tests']['objective_success'], 0)
        self.assertEqual(context['recent_episodes'][0]['tool_observations'][0]['result']['failed'], 2)
        self.store.record_objective_outcome(ep, False, {'failed_tests': ['edge-case']})
        context = self.store.context()
        self.assertEqual((context['objective_failure'], context['objective_pending']), (1, 0))
        self.assertEqual(context['recent_failures'][0]['evidence']['failed_tests'], ['edge-case'])
        self.assertEqual(context['tools']['run_tests']['objective_failure'], 1)

    def test_objective_resolution_immutable_and_persistent(self):
        ep = self.store.record_episode({'objective': 'Fix', 'tool_observations': []})
        self.store.record_objective_outcome(ep, True, {'checked': 'independent'})
        self.store.record_objective_outcome(ep, True, {'checked': 'independent'})
        with self.assertRaises(ValueError):
            self.store.record_objective_outcome(ep, False, {'checked': 'different'})
        self.assertEqual(ExperienceStore(self.temp.name).context()['objective_success'], 1)

    def test_proposal_does_not_self_verify(self):
        spec = {**self.spec, 'status': 'verified'}
        cap = self.store.propose(spec)
        self.assertEqual(self.store.get_capability(cap)['status'], 'proposed')
        self.assertEqual(self.store.propose(self.spec), cap)
        with self.assertRaises(ValueError):
            self.store.propose({**self.spec, 'verified': True})
        self.assertEqual(len(self.store.list_capabilities('verified')), 0)

    def test_complete_evaluation_and_spec_binding(self):
        cap = self.store.propose(self.spec)
        record = self.store.get_capability(cap)
        self.assertEqual(record['capability_sha256'], capability_sha256(record['spec']))
        self.assertEqual(self.store.record_evaluation(cap, self.evidence(cap))['status'], 'verified')
        record['spec']['name'] = 'mutated return object'
        self.assertEqual(self.store.get_capability(cap)['spec']['name'], self.spec['name'])
        self.assertEqual(len(self.store.list_capabilities('verified')), 1)
        bad = self.evidence(cap)
        bad['capability_sha256'] = 'f'*64
        with self.assertRaises(ValueError):
            self.store.record_evaluation(cap, bad)

    def test_incomplete_failed_or_duplicate_evidence_cannot_verify(self):
        cap = self.store.propose(self.spec)
        variants = []
        for change in ({'results': []}, {'fixtures': [], 'results': [], 'fixture_count': 0},
                       {'fixture_count': 2}, {'verifier_version': ''}, {'contract_id': 'different-contract'}):
            variants.append({**self.evidence(cap), **change})
        failed = self.evidence(cap)
        failed['results'][0]['passed'] = False
        variants.append(failed)
        duplicate = self.evidence(cap)
        duplicate['results'] *= 2
        variants.append(duplicate)
        missing_hash = self.evidence(cap)
        missing_hash['fixtures'][0]['input_sha256'] = 'not-a-hash'
        variants.append(missing_hash)
        for bad in variants:
            with self.assertRaises(ValueError):
                self.store.record_evaluation(cap, bad)
        self.assertEqual(self.store.get_capability(cap)['status'], 'proposed')
        self.assertEqual(self.store.record_evaluation(cap, self.evidence(cap, passed=False))['status'], 'failed')

    def test_unknown_contract_stays_unverified(self):
        cap = self.store.propose(self.spec)
        evidence = self.evidence(cap)
        evidence.update(status='needs_evaluation', contract_id='unsupported', fixtures=[], results=[], fixture_count=0)
        self.assertEqual(self.store.record_evaluation(cap, evidence)['status'], 'needs_evaluation')

    def test_corruption_and_missing_journal_fail_closed(self):
        ep = self.store.record_episode({'objective': 'Inspect'})
        original = json.loads(self.store.path.read_text())
        original['state']['events'][0]['data']['episode']['objective'] = 'changed'
        self.store.path.write_text(json.dumps(original))
        with self.assertRaises(MemoryIntegrityError):
            self.store.context()
        self.store.path.unlink()
        with self.assertRaises(MemoryIntegrityError):
            ExperienceStore(self.temp.name)

    def test_chain_detects_modified_record_even_if_outer_hash_recomputed(self):
        self.store.record_episode({'objective': 'Inspect'})
        envelope = json.loads(self.store.path.read_text())
        envelope['state']['events'][0]['data']['episode']['objective'] = 'changed'
        envelope['sha256'] = capability_sha256(envelope['state'])
        self.store.path.write_text(json.dumps(envelope))
        with self.assertRaises(MemoryIntegrityError):
            self.store.context()

    def test_concurrent_processes_preserve_all_episodes(self):
        ctx = multiprocessing.get_context('fork')
        processes = [ctx.Process(target=_append_from_process, args=(self.temp.name, i)) for i in range(4)]
        for p in processes:
            p.start()
        for p in processes:
            p.join(10)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(self.store.context()['episodes'], 4)

    def test_context_bounds_large_outputs(self):
        self.store.record_episode({'objective': 'Test', 'tool_observations': [
            {'tool': 'run_tests', 'execution_success': True, 'result': 'x'*100000}]})
        observation = self.store.context()['recent_episodes'][0]['tool_observations'][0]
        self.assertTrue(observation['truncated'])
        self.assertLessEqual(len(observation['summary_json_prefix']), 2000)
