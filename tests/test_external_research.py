import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ascendra.external_research import (
    IsolatedEvaluatorSandbox, PASS_MARKER, STRATEGY_IDS, aggregate,
    schedule, selected_ids, sha, sign_pvalue, task_statistics,
    verify_preregistration,
)
from ascendra.models import TaskResult
from ascendra.subscription import ProviderBlocked


class ExternalResearchTest(unittest.TestCase):
    def test_task_selection_is_fixed_and_order_independent(self):
        ids=[f'HumanEval/{i}' for i in range(164)]
        self.assertEqual(selected_ids(ids),selected_ids(ids[::-1]))
        self.assertEqual(len(set(selected_ids(ids))),20)

    def test_pairs_are_adjacent_and_order_balanced(self):
        ids=[f'task{i}' for i in range(20)]
        planned=schedule(ids)
        self.assertEqual(len(planned),120)
        for rep in range(1,4):
            pairs=[x for x in planned if x['replicate']==rep]
            for left,right in zip(pairs[::2],pairs[1::2]):
                self.assertEqual(left['task_id'],right['task_id'])
                self.assertEqual({left['strategy_id'],right['strategy_id']},set(STRATEGY_IDS))
            self.assertEqual(sum(p['strategy_id']==STRATEGY_IDS[0] for p in pairs[::2]),10)

    def test_task_cluster_test_does_not_count_replicates_as_new_tasks(self):
        self.assertEqual(sign_pvalue(0,0),1)
        self.assertEqual(sign_pvalue(1,0),0.5)
        self.assertEqual(sign_pvalue(5,0),1/32)
        old=[aggregate('g0',[TaskResult('same-task','g0',False,1,0)]) for _ in range(3)]
        new=[aggregate('g1',[TaskResult('same-task','g1',True,0,0)]) for _ in range(3)]
        stats=task_statistics(old,new)
        self.assertEqual(stats['task_wins'],1)
        self.assertEqual(stats['one_sided_sign_p'],0.5)

    def test_preregistration_detects_source_and_registration_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);study=root/'.ascendra/external-humaneval-v1';study.mkdir(parents=True)
            (root/'source.py').write_text('original')
            raw=json.dumps({'files':{'source.py':sha(b'original')}}).encode()
            (study/'preregistration.json').write_bytes(raw)
            (study/'preregistration.sha256').write_text(sha(raw))
            verify_preregistration(root)
            (root/'source.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen study'):verify_preregistration(root)
            (study/'preregistration.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Preregistration was modified'):verify_preregistration(root)

    def test_evaluator_has_no_host_root_or_network_and_readonly_task(self):
        with tempfile.TemporaryDirectory() as td:
            sandbox=IsolatedEvaluatorSandbox(Path(td))
            cmd=sandbox.command(Path(td),['python3','-I','/task/.ascendra_hidden/check.py'])
            self.assertIn('--unshare-all',cmd)
            self.assertNotIn('--share-net',cmd)
            self.assertNotIn('/',cmd)
            self.assertNotIn('--bind',cmd)
            self.assertIn('--ro-bind',cmd)

    def test_exit_zero_without_completed_tests_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as td:
            sandbox=IsolatedEvaluatorSandbox(Path(td))
            command=['python3','-I','/task/.ascendra_hidden/check.py']
            with patch('ascendra.external_research.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')):
                self.assertNotEqual(sandbox.run(Path(td),command,1)[0],0)
            with patch('ascendra.external_research.subprocess.run',return_value=subprocess.CompletedProcess([],0,PASS_MARKER+'\n','')):
                self.assertEqual(sandbox.run(Path(td),command,1)[0],0)

    def test_bwrap_failure_invalidates_study_not_task_score(self):
        with tempfile.TemporaryDirectory() as td:
            sandbox=IsolatedEvaluatorSandbox(Path(td))
            with patch('ascendra.external_research.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','bwrap: denied')):
                with self.assertRaises(ProviderBlocked):
                    sandbox.run(Path(td),['python3','-I','/task/.ascendra_hidden/check.py'],1)
