"""Independent ambition checks: measured progress is distinct from declarations."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest

from ascendra.capability_memory import ExperienceStore
from ascendra.capability_ambition import AmbitionBoard
from ascendra.capability_tools import ToolCatalog
from ascendra.capability_cli import run_episode


def ambition_plan(metric='verified_objectives', contract='unit-check-v1'):
    return dict(north_star='Independently improve Python project correctness.', goals=[
        dict(horizon=horizon, title='Improve '+horizon, why='Measured evidence is incomplete.',
             next_step='Inspect a new failure and verify the correction.', metric=metric,
             contract_id=contract, target=1)
        for horizon in ('now', 'next', 'stretch')])


class FakeDecider:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.requests = []

    def __call__(self, request, schema):
        self.requests.append(deepcopy(request))
        return deepcopy(next(self.actions))


def finish():
    return dict(action='finish', tool=None, arguments_json=None, proposal_json=None,
                message='All ambitions achieved; I am now an expert.')


def specification(name='Inspect source'):
    return dict(name=name, description='Inspect a Python source file.',
                motivation='Learn repeatable inspection.', contract_id='inspection-v1',
                steps=[dict(tool='read_file', arguments={'path': 'subject.py'})],
                success_criteria='Independent inspection fixtures pass.')


def evaluated(store, identifier, passed=True):
    record = store.get_capability(identifier)
    return store.record_evaluation(identifier, dict(
        status='verified' if passed else 'failed', contract_id='inspection-v1',
        verifier_version='test-host-v1', capability_sha256=record['capability_sha256'],
        fixture_count=1,
        fixtures=[dict(id='opaque-fixture', input_sha256='a'*64, expected_sha256='b'*64)],
        results=[dict(fixture_id='opaque-fixture', passed=passed, actual_sha256='c'*64)]))


class AmbitionProgressEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ExperienceStore(self.root/'memory')

    def episode(self, **extra):
        return self.store.record_episode(dict(objective='Inspect source',
            objective_success=True, finish_message='I achieved every ambition.',
            tool_observations=[dict(tool='run_tests', execution_success=True)], **extra))

    def test_model_declarations_and_public_tool_success_are_not_progress(self):
        episode = self.episode()
        self.assertEqual(self.store.progress_evidence([episode]),
                         dict(objectives=[], capabilities=[]))

    def test_objective_evidence_is_scoped_and_requires_named_contract(self):
        relevant, unrelated, unnamed = (self.episode() for _ in range(3))
        self.store.record_objective_outcome(relevant, False,
            dict(contract_id='unit-check-v1', passed=0, total=1))
        self.store.record_objective_outcome(unrelated, True,
            dict(contract_id='unit-check-v1', passed=1, total=1))
        self.store.record_objective_outcome(unnamed, True, dict(note='No registered contract'))
        expected = [dict(episode_id=relevant, success=False, contract_id='unit-check-v1',
                         infrastructure_error=False)]
        self.assertEqual(self.store.progress_evidence([relevant, relevant, unnamed])['objectives'], expected)
        self.assertEqual(self.store.progress_evidence([])['objectives'], [])

    def test_only_evaluated_linked_capabilities_are_exposed_once(self):
        measured = self.store.propose(specification())
        proposed = self.store.propose(specification('Unverified proposal'))
        unrelated = self.store.propose(specification('Unrelated verified ability'))
        evaluated(self.store, measured)
        evaluated(self.store, unrelated)
        first = self.episode(proposal_ids=[measured, proposed])
        second = self.episode(proposal_ids=[measured])
        caps = self.store.progress_evidence([first, second])['capabilities']
        self.assertEqual(len(caps), 1)
        self.assertEqual({k: v for k, v in caps[0].items() if k != 'functional_sha256'},
                         dict(id=measured, contract_id='inspection-v1', status='verified'))
        self.assertEqual(len(caps[0]['functional_sha256']), 64)
        evaluated(self.store, measured, passed=False)
        self.assertEqual(self.store.progress_evidence([first])['capabilities'][0]['status'], 'failed')

    def test_unknown_scope_fails_closed_and_results_are_detached(self):
        with self.assertRaises(KeyError):
            self.store.progress_evidence(['unknown'])
        with self.assertRaises(ValueError):
            self.store.progress_evidence('episode-not-a-list')
        episode = self.episode()
        self.store.record_objective_outcome(episode, True, dict(contract_id='unit-check-v1'))
        result = self.store.progress_evidence([episode])
        result['objectives'][0]['success'] = False
        self.assertTrue(self.store.progress_evidence([episode])['objectives'][0]['success'])

    def test_sandbox_infrastructure_error_is_distinct_from_candidate_runtime_failure(self):
        sandbox, candidate, explicit = (self.episode() for _ in range(3))
        self.store.record_objective_outcome(sandbox, False,
            dict(contract_id='unit-check-v1', results=[dict(status='sandbox_error')]))
        self.store.record_objective_outcome(candidate, False,
            dict(contract_id='unit-check-v1', results=[dict(status='runtime_error')]))
        self.store.record_objective_outcome(explicit, False,
            dict(contract_id='unit-check-v1', infrastructure_error=True))
        evidence = {e['episode_id']: e for e in
                    self.store.progress_evidence([sandbox, candidate, explicit])['objectives']}
        self.assertTrue(evidence[sandbox]['infrastructure_error'])
        self.assertTrue(evidence[explicit]['infrastructure_error'])
        self.assertFalse(evidence[candidate]['infrastructure_error'])


class AmbitionWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root/'project'
        self.project.mkdir()
        (self.project/'subject.py').write_text('VALUE = 0\n')
        self.catalog = ToolCatalog(self.project, writable_paths=['subject.py'])
        self.store = ExperienceStore(self.root/'memory')
        self.board = AmbitionBoard(self.root/'ambitions', 'Improve this Python project.')
        self.contracts = dict(verified_objectives=['unit-check-v1'],
                              verified_capabilities=['inspection-v1'])

    def episode(self, decider, name='episode', goal='Read the source.', **kwargs):
        with redirect_stdout(io.StringIO()):
            return run_episode(self.catalog, self.store, decider, goal, self.root/name,
                               max_steps=2, ambition=self.board, **kwargs)

    def test_ambition_persists_but_finish_claim_cannot_advance_it(self):
        self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        decider = FakeDecider([finish()])
        first = self.episode(decider)
        self.assertEqual(first['ambition']['challenge_level'], 1)
        self.assertEqual(first['ambition']['goals'][0]['measured'], 0)
        self.assertEqual(first['ambition']['goals'][0]['attempts'], 1)
        self.board = AmbitionBoard(self.root/'ambitions', self.board.mission)
        second_decider = FakeDecider([finish()])
        self.episode(second_decider, name='episode-2')
        self.assertEqual(len(second_decider.requests), 1)
        self.assertEqual(second_decider.requests[0]['ambition']['north_star'], ambition_plan()['north_star'])
        self.assertEqual(second_decider.requests[0]['goal'], 'Read the source.')

    def test_trusted_success_changes_next_goal_context_without_expanding_tools(self):
        def verifier():
            return dict(success=True, contract_id='unit-check-v1', passed=1, total=1)
        verifier.contract_id = 'unit-check-v1'
        first = self.episode(FakeDecider([ambition_plan(), finish()]), verifier=verifier)
        self.assertEqual(first['ambition']['goals'][0]['status'], 'metric_met')
        self.assertEqual(first['ambition']['challenge_level'], 2)
        self.assertEqual(first['ambition']['active_goal']['horizon'], 'next')
        choice = dict(goal='Inspect a harder variation.', rationale='The first metric has evidence.',
                      target_capability='Source diagnosis')
        decider = FakeDecider([choice, finish()])
        self.episode(decider, name='episode-2', goal=None, mission=self.board.mission)
        self.assertEqual(decider.requests[0]['ambition']['active_goal']['horizon'], 'next')
        self.assertEqual(decider.requests[1]['ambition']['active_goal']['horizon'], 'next')
        self.assertEqual(decider.requests[1]['goal'], choice['goal'])
        self.assertEqual(decider.requests[1]['tool_catalog'], self.catalog.descriptors())
        self.assertEqual(self.catalog.execute('write_file', dict(path='unauthorized.py', content=''))['status'], 'error')

    def test_failed_independent_outcome_guides_diagnostic_task(self):
        def verifier():
            return dict(success=False, contract_id='unit-check-v1', passed=0, total=1)
        verifier.contract_id = 'unit-check-v1'
        first = self.episode(FakeDecider([ambition_plan(), finish()]), verifier=verifier)
        self.assertEqual(first['ambition']['active_goal']['next_action'], 'diagnose_and_reduce_scope')
        self.assertEqual(first['ambition']['challenge_level'], 1)
        decider = FakeDecider([finish()])
        self.episode(decider, name='episode-2')
        self.assertEqual(decider.requests[0]['ambition']['active_goal']['failures'], 1)
        self.assertIn('smaller diagnostic task', decider.requests[0]['instruction'])

    def test_replay_cannot_pay_two_goals_and_old_success_is_not_ambient_credit(self):
        old = self.store.record_episode(dict(objective='Old work'))
        self.store.record_objective_outcome(old, True, dict(contract_id='unit-check-v1'))
        context = self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        self.assertEqual(context['goals'][0]['measured'], 0)
        episode = self.store.record_episode(dict(objective='Current work'))
        self.store.record_objective_outcome(episode, True, dict(contract_id='unit-check-v1'))
        self.board.attach(episode, context['goals'][0]['id'])
        self.board.attach(episode, context['goals'][0]['id'])
        with self.assertRaises(ValueError):
            self.board.attach(episode, context['goals'][1]['id'])
        rebuilt = AmbitionBoard(self.root/'ambitions', self.board.mission).context(self.store)
        self.assertEqual([goal['measured'] for goal in rebuilt['goals']], [1, 0, 0])
        self.assertEqual(rebuilt['goals'][0]['attempts'], 1)

    def test_preexisting_capabilities_and_duplicate_proposals_do_not_pay_twice(self):
        existing = self.store.propose(specification('Old capability'))
        evaluated(self.store, existing)
        context = self.board.ensure_plan(self.store,
            FakeDecider([ambition_plan('verified_capabilities', 'inspection-v1')]), self.contracts)
        first = self.store.record_episode(dict(objective='Repropose old capability', proposal_ids=[existing]))
        self.board.attach(first, context['goals'][0]['id'])
        self.assertEqual(self.board.context(self.store)['goals'][0]['measured'], 0)
        novel_spec = specification('New capability')
        novel_spec['steps'].append(dict(tool='list_files', arguments={}))
        novel = self.store.propose(novel_spec)
        evaluated(self.store, novel)
        second = self.store.record_episode(dict(objective='Develop new capability', proposal_ids=[novel]))
        third = self.store.record_episode(dict(objective='Repropose same capability', proposal_ids=[novel]))
        self.board.attach(second, context['goals'][0]['id'])
        self.board.attach(third, context['goals'][1]['id'])
        self.assertEqual([g['measured'] for g in self.board.context(self.store)['goals']], [1, 0, 0])

    def test_cosmetic_renaming_cannot_create_new_ambition_credit(self):
        old = self.store.propose(specification('Previous inspection'))
        evaluated(self.store, old)
        context = self.board.ensure_plan(self.store,
            FakeDecider([ambition_plan('verified_capabilities', 'inspection-v1')]), self.contracts)
        renamed_spec = specification('Much more ambitious inspection')
        renamed_spec['motivation'] = 'A brand new claim about the same workflow.'
        renamed = self.store.propose(renamed_spec)
        evaluated(self.store, renamed)
        episode = self.store.record_episode(dict(objective='Rename known skill', proposal_ids=[renamed]))
        self.board.attach(episode, context['goals'][0]['id'])
        self.assertNotEqual(old, renamed)
        self.assertEqual(self.board.context(self.store)['goals'][0]['measured'], 0)

    def test_unverifiable_ambitions_pause_without_spending_action_calls(self):
        decider = FakeDecider([ambition_plan(contract='future-verifier')])
        result = self.episode(decider, goal=None)
        self.assertEqual(result['stop_reason'], 'ambition_waiting_for_evidence')
        self.assertEqual(len(decider.requests), 1)
        self.assertEqual(self.store.context()['episodes'], 0)
        self.assertIsNone(result['ambition']['active_goal'])

    def test_two_failed_evaluations_require_revision_instead_of_blind_retries(self):
        initial = self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        for _ in range(2):
            episode = self.store.record_episode(dict(objective='Failed correction'))
            self.store.record_objective_outcome(episode, False, dict(contract_id='unit-check-v1'))
            self.board.attach(episode, initial['goals'][0]['id'])
        context = self.board.context(self.store)
        self.assertEqual(context['goals'][0]['status'], 'needs_revision')
        self.assertEqual(context['goals'][0]['next_action'], 'diagnose_and_reduce_scope')
        self.assertEqual(context['active_goal']['horizon'], 'next')
        self.assertEqual(context['challenge_level'], 1)

    def test_two_unverified_attempts_wait_for_evidence_without_claiming_failure(self):
        initial = self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        for _ in range(2):
            episode = self.store.record_episode(dict(objective='Unverified work', objective_success=True))
            self.board.attach(episode, initial['goals'][0]['id'])
        context = self.board.context(self.store)
        self.assertEqual(context['goals'][0]['status'], 'awaiting_evidence')
        self.assertEqual(context['goals'][0]['failures'], 0)
        self.assertEqual(context['goals'][0]['measured'], 0)

    def test_infrastructure_failure_does_not_lower_assessment_of_capability(self):
        initial = self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        for _ in range(2):
            episode = self.store.record_episode(dict(objective='Correction with unavailable evaluator'))
            self.store.record_objective_outcome(episode, False,
                dict(contract_id='unit-check-v1', results=[dict(status='sandbox_error')]))
            self.board.attach(episode, initial['goals'][0]['id'])
        context = self.board.context(self.store)
        self.assertEqual(context['goals'][0]['status'], 'awaiting_evidence')
        self.assertEqual(context['goals'][0]['failures'], 0)
        self.assertEqual(context['goals'][0]['measured'], 0)
        self.assertEqual(context['goals'][0]['next_action'], 'work_on_next_step')

    def test_all_attained_metrics_generate_one_new_persistent_plan(self):
        initial = self.board.ensure_plan(self.store, FakeDecider([ambition_plan()]), self.contracts)
        for goal in initial['goals']:
            episode = self.store.record_episode(dict(objective=goal['title']))
            self.store.record_objective_outcome(episode, True, dict(contract_id='unit-check-v1'))
            self.board.attach(episode, goal['id'])
        self.assertIsNone(self.board.context(self.store)['active_goal'])
        planner = FakeDecider([ambition_plan()])
        refreshed = self.board.ensure_plan(self.store, planner, self.contracts)
        self.assertEqual(refreshed['generation'], 1)
        self.assertEqual(refreshed['challenge_level'], 4)
        self.assertEqual([g['measured'] for g in refreshed['goals']], [0, 0, 0])
        self.assertTrue(all(g['status'] == 'metric_met' for g in refreshed['history'][0]['goals']))
        self.assertEqual(planner.requests[0]['previous_ambitions']['challenge_level'], 4)
        self.board.ensure_plan(self.store, planner, self.contracts)
        self.assertEqual(len(planner.requests), 1)
        restarted = AmbitionBoard(self.root/'ambitions', self.board.mission).context(self.store)
        self.assertEqual(restarted['generation'], 1)
        self.assertEqual(restarted['goals'], refreshed['goals'])


if __name__ == '__main__':
    unittest.main()
