from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ascendra import capability_cli as cli
from ascendra.capability_memory import ExperienceStore
from ascendra.capability_tools import ToolCatalog
from ascendra.v4_ledger import BudgetExceeded, ProviderFailure


class FakeDecider:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.requests = []

    def __call__(self, request, schema):
        self.requests.append(deepcopy(request))
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return deepcopy(action)


def action(tool, arguments):
    return {'action': 'tool', 'tool': tool, 'arguments_json': json.dumps(arguments),
            'proposal_json': None, 'message': None}


def finish():
    return {'action': 'finish', 'tool': None, 'arguments_json': None,
            'proposal_json': None, 'message': 'Done; independent verification is separate.'}


class CapabilityEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'tests').mkdir()
        (self.project / 'subject.py').write_text('VALUE = 0\n')
        (self.project / 'tests' / 'test_subject.py').write_text(
            'import unittest\nfrom subject import VALUE\nclass Check(unittest.TestCase):\n'
            ' def test_value(self): self.assertEqual(VALUE, 1)\n')
        self.catalog = ToolCatalog(self.project, writable_paths=['subject.py'])
        self.store = ExperienceStore(self.root / 'memory')

    def run_episode(self, decider, goal='Repair the constant.', **kwargs):
        with redirect_stdout(io.StringIO()):
            return cli.run_episode(self.catalog, self.store, decider, goal,
                                    self.root / 'episode', **kwargs)

    def test_fake_decider_real_tools_fix_and_trusted_objective_are_recorded(self):
        decider = FakeDecider([action('run_tests', {}),
                               action('write_file', {'path': 'subject.py', 'content': 'VALUE = 1\n'}),
                               action('run_tests', {}), finish()])
        result = self.run_episode(decider, max_steps=4,
            verifier=lambda: {'success': (self.project/'subject.py').read_text() == 'VALUE = 1\n',
                              'check': 'Trusted fixture source comparison'})
        self.assertEqual(result['selected_tools'], ['run_tests', 'write_file', 'run_tests'])
        self.assertTrue(result['objective']['success'])
        first = decider.requests[1]['recent_results'][0]['result']
        self.assertEqual(first['status'], 'ok')
        self.assertFalse(first['data']['successful'])
        self.assertTrue(decider.requests[3]['recent_results'][-1]['result']['data']['successful'])
        self.assertEqual(self.store.context()['objective_success'], 1)
        for name in ('context_before', 'episode', 'summary', 'context_after'):
            self.assertTrue((self.root/'episode'/f'{name}.json').is_file())

    def test_one_step_limit_is_valid_and_does_not_claim_objective_success(self):
        result = self.run_episode(FakeDecider([finish()]), max_steps=1)
        self.assertEqual(result['stop_reason'], 'finished')
        self.assertIsNone(result['objective'])
        self.assertEqual(self.store.context()['objective_pending'], 1)

    def test_choose_goal_uses_prior_context_and_preserves_chosen_goal(self):
        decider = FakeDecider([{'goal': 'Read the source.', 'rationale': 'Need evidence.',
                               'target_capability': 'Source inspection'}, finish()])
        self.run_episode(decider, goal=None, mission='Inspect this project.', max_steps=1)
        self.assertEqual(decider.requests[0]['mission'], 'Inspect this project.')
        self.assertEqual(decider.requests[1]['goal'], 'Read the source.')
        choice = json.loads((self.root/'episode'/'chosen_goal.json').read_text())['payload']
        self.assertEqual(choice['goal'], 'Read the source.')

    def test_decider_failure_is_persisted_as_incomplete_without_retry(self):
        decider = FakeDecider([RuntimeError('transport unavailable')])
        result = self.run_episode(decider, max_steps=3)
        self.assertEqual(result['stop_reason'], 'decision_error')
        self.assertEqual(len(decider.requests), 1)
        self.assertEqual(self.store.context()['objective_pending'], 1)
        self.assertEqual(result['evaluations'], [])

    def test_episode_artifacts_and_memory_must_not_be_model_visible(self):
        for target in (self.project / 'traces', self.project):
            with self.subTest(target=target), self.assertRaises(ValueError):
                cli.run_episode(self.catalog, self.store, FakeDecider([finish()]), 'Inspect', target)
        self.assertFalse((self.project/'traces').exists())
        inside = ExperienceStore(self.project/'memory')
        with self.assertRaises(ValueError):
            cli.run_episode(self.catalog, inside, FakeDecider([finish()]), 'Inspect', self.root/'safe')
        self.assertFalse((self.root/'safe').exists())

    def test_grow_rejects_memory_symlink_and_run_symlink_before_provider(self):
        memory_link = self.root/'memory-link'
        memory_link.symlink_to(self.project, target_is_directory=True)
        (self.root/'memory'/'runs').symlink_to(self.project, target_is_directory=True)
        for memory in (memory_link, self.root/'memory'):
            args = SimpleNamespace(project=str(self.project), memory=str(memory), model='fake',
                                   effort='low', allow_write=[], max_steps=1, cycles=1, goal='Inspect')
            with patch.object(cli, 'SubscriptionDecider') as provider, self.assertRaises(ValueError):
                cli.grow(args)
            provider.assert_not_called()

    def test_invalid_write_scope_is_rejected_before_provider_creation(self):
        args = SimpleNamespace(project=str(self.project), memory=str(self.root/'new-memory'), model='fake',
                               effort='low', allow_write=['../outside.py'], max_steps=1, cycles=1, goal='Inspect')
        with patch.object(cli, 'SubscriptionDecider') as provider, self.assertRaises(ValueError):
            cli.grow(args)
        provider.assert_not_called()
        self.assertFalse((self.root/'new-memory').exists())

    def test_cli_limits_reject_invalid_values_without_provider(self):
        for option, value in (('--max-steps', '0'), ('--max-steps', '33'), ('--cycles', '0')):
            with self.subTest(option=option, value=value), patch.object(cli, 'SubscriptionDecider') as provider:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    cli.main(['grow', '--project', str(self.project), '--memory', str(self.root/'elsewhere'),
                              option, value])
                self.assertEqual(raised.exception.code, 2)
                provider.assert_not_called()


class FakeProvider:
    def __init__(self, **kwargs):
        self.call_records = []
        self.behavior = 'success'
        self.physical_calls = 0

    def verify_isolation(self):
        pass

    def _exec(self, request, schema):
        self.physical_calls += 1
        if self.behavior == 'missing_record':
            return finish()
        record = {'status': 'completed', 'tool_calls': 0, 'total_tokens': 17, 'cost': None}
        if self.behavior == 'unknown_usage':
            record['total_tokens'] = None
        if self.behavior == 'invalid_tools':
            record['tool_calls'] = 1
        if self.behavior == 'failure':
            record.update(status='error', total_tokens=23)
        self.call_records.append(record)
        if self.behavior == 'failure':
            raise RuntimeError('provider failure after usage')
        return finish()


class SubscriptionAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.patch = patch.object(cli, 'SubscriptionProvider', FakeProvider)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.decider = cli.SubscriptionDecider(Path(self.temporary.name)/'provider', max_calls=3)

    def decide(self):
        with redirect_stdout(io.StringIO()):
            return self.decider({'goal': 'Inspect'}, {'type': 'object'})

    def test_completed_and_failed_calls_both_account_actual_usage(self):
        self.assertEqual(self.decide()['action'], 'finish')
        self.decider.provider.behavior = 'failure'
        with self.assertRaises(ProviderFailure): self.decide()
        summary = self.decider.ledger.summary()
        self.assertEqual(summary['calls'], 2)
        self.assertEqual(summary['known_tokens'], 40)
        self.assertEqual(summary['unknown_usage_calls'], 0)
        self.assertEqual(self.decider.provider.physical_calls, 2)

    def test_missing_record_never_reuses_previous_usage(self):
        self.decide()
        self.decider.provider.behavior = 'missing_record'
        with self.assertRaises(ProviderFailure): self.decide()
        summary = self.decider.ledger.summary()
        self.assertEqual(summary['known_tokens'], 17)
        self.assertEqual(summary['unknown_usage_calls'], 1)
        self.assertEqual(summary['accounted_tokens'], 50017)

    def test_unknown_usage_fails_closed_and_retains_full_reservation(self):
        self.decider.provider.behavior = 'unknown_usage'
        with self.assertRaises(ProviderFailure): self.decide()
        summary = self.decider.ledger.summary()
        self.assertEqual(summary['calls'], 1)
        self.assertEqual(summary['unknown_usage_calls'], 1)
        self.assertEqual(summary['accounted_tokens'], 50000)

    def test_provider_tool_execution_is_rejected_but_counted(self):
        self.decider.provider.behavior = 'invalid_tools'
        with self.assertRaises(ProviderFailure): self.decide()
        self.assertEqual(self.decider.ledger.summary()['known_tokens'], 17)

    def test_call_budget_stops_before_next_physical_call(self):
        for _ in range(3): self.decide()
        with self.assertRaises(BudgetExceeded): self.decide()
        self.assertEqual(self.decider.provider.physical_calls, 3)
        self.assertEqual(self.decider.ledger.summary()['calls'], 3)


if __name__ == '__main__':
    unittest.main()
