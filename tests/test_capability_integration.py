"""Capability integration checks use synthetic projects and no model network calls."""
import hashlib
import json
import socket
from pathlib import Path
import tempfile
import unittest


class CapabilityToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        from ascendra.capability_tools import ToolCatalog
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'project'
        self.root.mkdir()
        (self.root/'tests').mkdir()
        (self.root/'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.root/'tests'/'test_calc.py').write_text(
            'import unittest\nfrom calc import add\n'
            'class Tests(unittest.TestCase):\n'
            '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
        self.catalog = ToolCatalog(self.root, writable_paths=['calc.py'])

    def test_test_command_success_is_not_test_success_and_real_fix_is_observed(self):
        failed = self.catalog.execute('run_tests', {'start_dir': 'tests', 'pattern': 'test*.py'})
        self.assertEqual(failed['status'], 'ok')
        self.assertFalse(failed['data']['successful'])
        self.assertEqual(failed['data']['tests_run'], 1)
        self.assertEqual(failed['data']['failures'], 1)
        old = hashlib.sha256((self.root/'calc.py').read_bytes()).hexdigest()
        write = self.catalog.execute('write_file', {'path': 'calc.py', 'content': 'def add(a, b):\n    return a + b\n', 'expected_sha256': old})
        self.assertEqual(write['status'], 'ok')
        passed = self.catalog.execute('run_tests', {'start_dir': 'tests', 'pattern': 'test*.py'})
        self.assertTrue(passed['data']['successful'])
        self.assertEqual(passed['data']['tests_run'], 1)

    def test_empty_test_discovery_is_not_success(self):
        result = self.catalog.execute('run_tests', {'start_dir': 'tests', 'pattern': 'absent*.py'})
        self.assertFalse(result['data']['successful'])
        self.assertEqual(result['data']['tests_run'], 0)

    def test_cannot_rewrite_evaluator_tests_or_escape_project(self):
        before = (self.root/'tests'/'test_calc.py').read_text()
        for name in ('tests/test_calc.py', '../outside.py', '/tmp/capability_escape.py'):
            with self.subTest(path=name):
                result = self.catalog.execute('write_file', {'path': name, 'content': 'pass\n'})
                self.assertEqual(result['status'], 'error')
        self.assertEqual((self.root/'tests'/'test_calc.py').read_text(), before)
        self.assertFalse((self.root.parent/'outside.py').exists())

    def test_private_and_symlink_paths_are_unavailable(self):
        secret = self.root.parent/'secret.txt'
        secret.write_text('PRIVATE_SENTINEL')
        (self.root/'shortcut').symlink_to(secret)
        (self.root/'.ascendra_hidden').mkdir()
        (self.root/'.ascendra_hidden'/'cases.json').write_text('PRIVATE_SENTINEL')
        for name in ('shortcut', '../secret.txt', '.ascendra_hidden/cases.json'):
            with self.subTest(path=name):
                result = self.catalog.execute('read_file', {'path': name})
                self.assertEqual(result['status'], 'error')
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        listing = self.catalog.execute('list_files', {})
        self.assertNotIn('.ascendra_hidden/cases.json', json.dumps(listing))
        result = self.catalog.execute('search_text', {'query': 'PRIVATE_SENTINEL'})
        self.assertNotIn('cases.json', json.dumps(result))
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result.get('data', {})))

    def test_project_tests_cannot_mutate_live_source(self):
        source = (self.root/'calc.py').read_text()
        (self.root/'tests'/'test_calc.py').write_text(
            'import unittest\nfrom pathlib import Path\n'
            'class Tests(unittest.TestCase):\n'
            '    def test_mutation(self):\n'
            '        with self.assertRaises(OSError):\n'
            '            Path("calc.py").write_text("tampered")\n')
        result = self.catalog.execute('run_tests', {'start_dir': 'tests', 'pattern': 'test*.py'})
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['data']['successful'])
        self.assertEqual((self.root/'calc.py').read_text(), source)


    def test_test_runner_cannot_connect_to_host_loopback(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0)); server.listen(1)
            port = server.getsockname()[1]
            (self.root/'tests'/'test_calc.py').write_text(
                'import unittest, socket\n'
                'class Tests(unittest.TestCase):\n'
                '    def test_network(self):\n'
                '        with self.assertRaises(OSError):\n'
                f'            socket.create_connection(("127.0.0.1", {port}), timeout=0.5)\n')
            result = self.catalog.execute('run_tests', {'start_dir': 'tests', 'pattern': 'test*.py'})
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['data']['successful'])


class CapabilityEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        from ascendra.capability_memory import ExperienceStore
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = ExperienceStore(Path(self.temporary.name)/'memory')
        self.spec = {'name': 'Inspect Python tests', 'description': 'Run tests and inspect source.',
                     'motivation': 'Observed tests can fail although command execution succeeds.',
                     'steps': [{'tool': 'run_tests', 'arguments': {'start_dir': 'tests', 'pattern': 'test*.py'}}],
                     'success_criteria': 'Independently observe expected test failures and source evidence.'}

    def test_model_episode_success_flag_is_not_a_verified_outcome(self):
        self.store.record_episode({'objective': 'Fix addition', 'objective_success': True,
                                   'tool_observations': []})
        context = self.store.context()
        self.assertEqual(context['objective_success'], 0)
        self.assertEqual(context['objective_pending'], 1)

    def test_proposal_cannot_self_verify_or_bypass_complete_evidence(self):
        with self.assertRaises(ValueError):
            self.store.propose(dict(self.spec, verified=True))
        identifier = self.store.propose(dict(self.spec, status='verified'))
        saved = self.store.get_capability(identifier)
        self.assertEqual(saved['status'], 'proposed')
        self.assertEqual(saved['spec']['steps'], self.spec['steps'])
        forged = {'contract_id': 'python_test_diagnosis', 'verifier_version': 'fake',
                  'capability_sha256': saved['capability_sha256'], 'fixture_count': 1,
                  'fixtures': [{'id': 'required', 'input_sha256': 'a'*64, 'expected_sha256': 'b'*64}],
                  'results': [], 'status': 'verified'}
        with self.assertRaises(ValueError):
            self.store.record_evaluation(identifier, forged)
        self.assertEqual(self.store.get_capability(identifier)['status'], 'proposed')

    def test_unverifiable_proposals_persist_unresolved_without_fake_failed_fixtures(self):
        from ascendra.capability_evaluator import evaluate_capability
        for spec in (self.spec, dict(self.spec, contract_id='python_test_diagnosis')):
            identifier = self.store.propose(spec)
            evidence = evaluate_capability(self.store.get_capability(identifier)['spec'])
            self.assertEqual(evidence['status'], 'needs_evaluation')
            self.assertEqual(evidence['fixtures'], [])
            result = self.store.record_evaluation(identifier, evidence)
            self.assertEqual(result['status'], 'needs_evaluation')

    def test_trusted_failed_outcome_remains_failed_after_reopening(self):
        from ascendra.capability_memory import ExperienceStore
        identifier = self.store.record_episode({'objective': 'Fix addition', 'objective_success': None,
            'tool_observations': [{'tool': 'run_tests', 'execution_success': True, 'objective_success': None}]})
        self.store.record_objective_outcome(identifier, False, {'assertion': 'add(2,3) must equal 5'})
        reopened = ExperienceStore(Path(self.temporary.name)/'memory')
        self.assertEqual(reopened.context()['objective_failure'], 1)
        self.assertEqual(reopened.context()['objective_success'], 0)
        with self.assertRaises(ValueError):
            reopened.record_objective_outcome(identifier, True, {'claim': 'Trust me'})


class CapabilityAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        from ascendra.capability_memory import ExperienceStore
        CapabilityToolIntegrationTests.setUp(self)
        self.store = ExperienceStore(Path(self.temporary.name)/'memory')

    def test_recorded_failure_is_supplied_and_changes_next_scripted_tool_choice(self):
        from ascendra.capability_agent import CapabilityAgent
        requests = []
        def planner(request, schema):
            requests.append(request)
            if request['recent_results']:
                return {'action': 'finish', 'message': 'Claimed finished; independent evaluation still required.'}
            if request['learned_context']['objective_failure']:
                return {'action': 'tool', 'tool': 'read_file', 'arguments': {'path': 'calc.py'}}
            return {'action': 'tool', 'tool': 'run_tests', 'arguments': {'start_dir': 'tests', 'pattern': 'test*.py'}}
        agent = CapabilityAgent(self.catalog, self.store, planner, max_steps=3)
        first = agent.run('Fix addition')
        self.assertIsNone(first['objective_success'])
        self.assertTrue(first['tool_observations'][0]['execution_success'])
        self.assertFalse(first['steps'][0]['result']['data']['successful'])
        self.store.record_objective_outcome(first['episode_id'], False,
                                           {'assertion': 'add(2,3) must equal 5; observed -1'})
        requests.clear()
        second = agent.run('Fix addition')
        self.assertEqual(second['steps'][0]['tool'], 'read_file')
        self.assertIn('add(2,3) must equal 5', json.dumps(requests[0]['learned_context']))
        self.assertIn('failures', json.dumps(requests[0]['learned_context']))
        self.assertIsNone(second['objective_success'])
        self.assertEqual(self.store.context()['objective_success'], 0)

    def test_proposed_workflow_is_callable_only_after_independent_fixture_verification(self):
        from ascendra.capability_agent import CapabilityAgent
        from ascendra.capability_evaluator import CONTRACTS, evaluate_capability
        contract = CONTRACTS['python_test_diagnosis']
        spec = {'name': 'Inspect actual Python failures', 'description': 'Read, search and execute the selected tests.',
                'motivation': 'Test-command execution is not the same as passing tests.',
                'contract_id': 'python_test_diagnosis',
                'input_schema': contract['input_schema'], 'steps': contract['required_steps'],
                'success_criteria': 'Preserve actual read/search/test observations on independent fixtures.'}
        def proposing_planner(request, schema):
            if not request['recent_results']:
                return {'action': 'propose', 'proposal': spec}
            if len(request['recent_results']) == 1:
                identifier = self.store.list_capabilities()[0]['id']
                return {'action': 'tool', 'tool': 'capability:'+identifier, 'arguments': {}}
            return {'action': 'finish', 'message': 'Proposal awaits independent verification.'}
        proposal_episode = CapabilityAgent(self.catalog, self.store, proposing_planner, max_steps=4).run('Develop an inspection workflow')
        identifier = proposal_episode['proposal_ids'][0]
        self.assertEqual(self.store.get_capability(identifier)['status'], 'proposed')
        self.assertEqual(proposal_episode['steps'][1]['result']['status'], 'error')
        saved_spec = self.store.get_capability(identifier)['spec']
        self.assertEqual(saved_spec['steps'], spec['steps'])
        evidence = evaluate_capability(saved_spec)
        self.assertEqual(evidence['status'], 'verified')
        self.assertEqual(evidence['fixture_count'], 3)
        self.assertEqual([r['details']['observed']['successful'] for r in evidence['results']], [True, False, False])
        self.store.record_evaluation(identifier, evidence)
        def reusing_planner(request, schema):
            if request['recent_results']:
                return {'action': 'finish', 'message': 'Diagnostic observations collected.'}
            names = {d['name'] for d in request['tool_catalog']}
            self.assertIn('capability:'+identifier, names)
            return {'action': 'tool', 'tool': 'capability:'+identifier,
                    'arguments': {'source_path': 'calc.py', 'test_dir': 'tests',
                                  'test_pattern': 'test*.py', 'query': 'add'}}
        result = CapabilityAgent(self.catalog, self.store, reusing_planner, max_steps=3).run('Inspect the failing project')
        self.assertEqual(result['steps'][0]['result']['status'], 'ok')
        executed = result['steps'][0]['result']['steps']
        self.assertEqual([step['tool'] for step in executed], ['read_file', 'search_text', 'run_tests'])
        self.assertFalse(executed[-1]['result']['data']['successful'])
        self.assertIsNone(result['objective_success'])
        self.assertEqual(self.store.context()['objective_success'], 0)


if __name__ == '__main__':
    unittest.main()
