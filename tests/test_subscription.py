import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ascendra.agent import EvolutionAgent
from ascendra.evolution import EvolutionEngine
from ascendra.models import EvalSummary, Strategy, TaskResult
from ascendra.promotion import PromotionGate
from ascendra.store import EvidenceStore
from ascendra.subscription import ProviderBlocked, SubscriptionProvider


class SubscriptionTest(unittest.TestCase):
    def provider(self):
        with patch('ascendra.subscription.shutil.which', return_value='/fake/binary'), \
                patch('ascendra.subscription.Path.is_file', return_value=True):
            return SubscriptionProvider(root='/workspace/ASCENDRA')

    def fake_run(self, extra=None, returncode=0):
        def run(command, **kwargs):
            Path(command[command.index('-o') + 1]).write_text('{"ready":true}')
            events = [extra] if extra else []
            events.append({'type': 'turn.completed', 'usage': {'input_tokens': 7, 'output_tokens': 3}})
            return subprocess.CompletedProcess(command, returncode,
                                               '\n'.join(json.dumps(e) for e in events), '')
        return run

    def test_pin_isolation_and_usage(self):
        provider = self.provider()
        with patch('ascendra.subscription.subprocess.run', side_effect=self.fake_run()) as run:
            self.assertEqual(provider._exec('{}', {}), {'ready': True})
        command = run.call_args.args[0]
        self.assertIn('--unshare-pid', command)
        self.assertIn(str(provider.root), command)
        self.assertIn('--tmpfs', command)
        self.assertEqual(command[command.index('--model')+1], 'gpt-6-astra')
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertEqual(provider.call_records[0]['total_tokens'], 10)
        self.assertEqual(provider.usage_snapshot()['model_calls'], 1)
        self.assertEqual(provider.call_records[0]['status'], 'completed')

    def test_tool_activity_invalidates_response(self):
        provider = self.provider()
        event = {'type': 'item.completed', 'item': {'type': 'command_execution'}}
        with patch('ascendra.subscription.subprocess.run', side_effect=self.fake_run(event)):
            with self.assertRaisesRegex(ProviderBlocked, 'Tool activity'):
                provider._exec('{}', {})
        self.assertEqual(provider.call_records[0]['status'], 'error')
        self.assertEqual(provider.call_records[0]['total_tokens'], 10)

    def test_disabled_host_notice_is_not_tool_activity(self):
        provider = self.provider()
        event = {'type': 'item.completed', 'item': {'type': 'error', 'message': provider.DISABLED_HOST_NOTICE}}
        with patch('ascendra.subscription.subprocess.run', side_effect=self.fake_run(event)):
            self.assertEqual(provider._exec('{}', {}), {'ready': True})
        self.assertTrue(provider.call_records[0]['code_mode_disabled'])
        self.assertEqual(provider.call_records[0]['tool_calls'], 0)

    def test_timeout_is_counted_without_invented_tokens(self):
        provider = self.provider()
        with patch('ascendra.subscription.subprocess.run', side_effect=subprocess.TimeoutExpired('codex', 1)):
            with self.assertRaises(ProviderBlocked): provider._exec('{}', {})
        self.assertEqual(provider.usage_snapshot()['model_calls'], 1)
        self.assertIsNone(provider.call_records[0]['input_tokens'])
        self.assertIsNone(provider.call_records[0]['cost'])

    def test_private_snapshot_never_reaches_provider(self):
        provider = self.provider()
        with patch.object(provider, '_exec') as call:
            with self.assertRaises(ProviderBlocked):
                provider.propose_edits(prompt='', task_id='sentinel', description='',
                                       files={'.ascendra_hidden/nested/test.py': 'private'})
            call.assert_not_called()

    def test_only_supplied_public_files_can_change(self):
        provider = self.provider()
        for path in ['.ascendra_hidden/test.py', '../task.py', 'unknown.py']:
            with self.subTest(path=path), patch.object(provider, '_exec', return_value={
                    'files': [{'path': path, 'content': 'replacement'}]}):
                with self.assertRaises(ProviderBlocked):
                    provider.propose_edits(prompt='', task_id='t', description='', files={'task.py': 'old'})

    def test_snapshot_and_replacements_end_to_end(self):
        provider = self.provider()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'task.py').write_text('old')
            (root/'.ascendra_hidden').mkdir()
            (root/'.ascendra_hidden/test.py').write_text('private sentinel')
            def reply(prompt, schema):
                self.assertEqual(json.loads(prompt)['public_files'], {'task.py': 'old'})
                self.assertNotIn('private sentinel', prompt)
                self.assertNotIn(td, prompt)
                return {'files': [{'path': 'task.py', 'content': 'new'}]}
            with patch.object(provider, '_exec', side_effect=reply):
                EvolutionAgent(provider).solve('strategy', 't', 'public task', root)
            self.assertEqual((root/'task.py').read_text(), 'new')
            self.assertEqual((root/'.ascendra_hidden/test.py').read_text(), 'private sentinel')

    @unittest.skipUnless(shutil.which('bwrap'), 'bubblewrap not installed')
    def test_real_filesystem_and_process_isolation(self):
        provider = self.provider()
        provider.bwrap = shutil.which('bwrap')
        with tempfile.TemporaryDirectory(dir=Path.cwd().parent) as td:
            parent = Path(td)
            provider.root = parent/'repository'
            provider.root.mkdir()
            provider.codex_directory = parent/'codex-state'
            provider.codex_directory.mkdir()
            provider.auth_file = provider.codex_directory/'auth.json'
            provider.auth_file.write_text('{}')
            provider.verify_isolation()


class EvidenceControlTest(unittest.TestCase):
    def test_mutation_does_not_receive_raw_evaluator_output(self):
        result = TaskResult('public-task', 'g0', False, 1, 0,
                            stdout='PRIVATE STDOUT', stderr='HIDDEN TEST SOURCE', error='PRIVATE ERROR')
        summary = EvalSummary('g0', 1, 0, 0, 0, 0, 1, 0, 0, [result])
        feedback = EvolutionEngine._failure_summary(summary)
        self.assertIn('public-task', feedback)
        self.assertNotIn('PRIVATE', feedback)
        self.assertNotIn('HIDDEN', feedback)

    def test_strategy_lineage_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            store = EvidenceStore(Path(td)/'evidence.db')
            store.save_strategy(Strategy('g0', 0, None, 'original'))
            store.save_strategy(Strategy('g0', 0, None, 'original'))
            with self.assertRaises(ValueError):
                store.save_strategy(Strategy('g0', 0, None, 'different'))
            row = store.export()['strategies'][0]
            self.assertEqual(row['prompt'], 'original')
            self.assertEqual(len(json.loads(row['metadata'])['prompt_sha256']), 64)

    def test_visible_regression_blocks_holdout_improvement(self):
        def summary(sid, visible, holdout):
            results = [TaskResult('visible', sid, visible, 0, 0)]
            results += [TaskResult(f'h{i}', sid, holdout, 0, 0) for i in range(4)]
            return EvalSummary(sid, 5, int(visible)+4*int(holdout), 0, 1, int(visible),
                               4, 4*int(holdout), 0, results)
        decision = PromotionGate().decide_repeated([summary('a', True, False)]*3,
                                                   [summary('b', False, True)]*3)
        self.assertFalse(decision.promote)
        self.assertEqual(decision.regressions, ['visible'])

    def test_three_discordant_pairs_are_inconclusive(self):
        def summary(sid, solved):
            return EvalSummary(sid, 1, int(solved), int(solved), 0, 0, 1, int(solved), 0,
                               [TaskResult('h', sid, solved, 0, 0)])
        decision = PromotionGate().decide_repeated([summary('a', False)]*3, [summary('b', True)]*3)
        self.assertFalse(decision.promote)
        self.assertEqual(decision.verdict, 'INCONCLUSIVE')
