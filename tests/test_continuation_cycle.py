import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ascendra.continuation_cycle import evaluate_candidate, propose_next_steps, tree_digest


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'baseline'
        self.candidate = Path(self.temp.name) / 'candidate'
        for path, text in ((self.base, 'old'), (self.candidate, 'new')):
            path.mkdir(); (path / 'code.py').write_text(text)

    def evaluate(self, callback, **kwargs):
        return evaluate_candidate(self.base, self.candidate, ['a', 'b'], evaluator=callback,
                                  evaluator_id='trusted-fixture-v1', **kwargs)

    def test_comparison_is_repeated_and_isolated(self):
        seen = []
        def evaluator(path, case, budget, repeat):
            self.assertNotIn(path, (self.base, self.candidate))
            new = (path / 'code.py').read_text() == 'new'
            seen.append((new, case, repeat, budget.copy()))
            budget['max_cost'] = 999
            return {'score': .8 if new else .5, 'cost': 0, 'seconds': 1}
        result = self.evaluate(evaluator)
        self.assertEqual(result['status'], 'eligible')
        self.assertFalse(result['promoted'])
        self.assertEqual(len(seen), 12)
        self.assertTrue(all(item[3]['max_cost'] == 0 for item in seen))
        self.assertFalse(seen[0][0]); self.assertTrue(seen[4][0])
        self.assertEqual(result['artifact_sha256']['candidate'], tree_digest(self.candidate))

    def test_regression_rejects_average_improvement(self):
        def evaluator(path, case, *unused):
            new = (path / 'code.py').read_text() == 'new'
            return {'score': (1 if case == 'a' else .4) if new else .5, 'cost': 0, 'seconds': 0}
        self.assertEqual(self.evaluate(evaluator)['status'], 'rejected')

    def test_limits_nonfinite_and_mutation_rejected(self):
        for result in ({'score': .9, 'cost': 1, 'seconds': 1},
                       {'score': float('nan'), 'cost': 0, 'seconds': 1},
                       {'score': .9, 'cost': 0, 'seconds': 61}):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.evaluate(lambda *args: result)
        def mutate(path, *args):
            (path / 'code.py').write_text('tampered')
            return {'score': 1, 'cost': 0, 'seconds': 0}
        with self.assertRaises(ValueError): self.evaluate(mutate)
        self.assertEqual((self.base / 'code.py').read_text(), 'old')

    def test_symlink_rejected(self):
        (self.candidate / 'outside').symlink_to(self.base / 'code.py')
        with self.assertRaises(ValueError): tree_digest(self.candidate)

    def test_research_failure_does_not_generate_or_approve(self):
        store = Mock()
        with patch('ascendra.continuation_cycle.research', return_value={'id': 'r', 'status': 'failed'}), patch('ascendra.continuation_cycle.generate_proposals') as generate:
            result = propose_next_steps(store, 'next', decide=Mock())
        self.assertEqual(result['status'], 'research_failed')
        generate.assert_not_called(); store.approve.assert_not_called(); store.save_batch.assert_not_called()

    def test_continuation_stops_at_selection(self):
        store = Mock(); evidence = {'id': 'r', 'status': 'complete'}
        batch = {'id': 'b', 'proposals': [1, 2, 3]}
        with patch('ascendra.continuation_cycle.research', return_value=evidence), patch('ascendra.continuation_cycle.generate_proposals', return_value=batch):
            result = propose_next_steps(store, 'next', decide=Mock())
        self.assertEqual(result['status'], 'awaiting_selection')
        self.assertFalse(result['execution_started'])
        store.save_research.assert_called_once_with(evidence)
        store.save_batch.assert_called_once_with(batch)
        store.approve.assert_not_called()


class VersionTests(unittest.TestCase):
    setUp = EvaluationTests.setUp
    evaluate = EvaluationTests.evaluate
    def report(self):
        return self.evaluate(lambda path, *args: {'score': .9 if (path / 'code.py').read_text() == 'new' else .5, 'cost': 0, 'seconds': 0})

    def test_promote_rollback_and_stale_guard(self):
        from ascendra.continuation_cycle import initialize_versions, promote_candidate, rollback_version
        registry = Path(self.temp.name) / 'registry'
        initial = initialize_versions(registry, self.base)
        report = self.report()
        with self.assertRaises(PermissionError):
            promote_candidate(registry, self.base, self.candidate, report, expected_current=initial['current'])
        new = promote_candidate(registry, self.base, self.candidate, report, expected_current=initial['current'], allow_promotion=True)
        self.assertEqual(new['current'], tree_digest(self.candidate))
        with self.assertRaises(ValueError):
            promote_candidate(registry, self.base, self.candidate, report, expected_current=initial['current'], allow_promotion=True)
        restored = rollback_version(registry, initial['current'], expected_current=new['current'], allow_rollback=True)
        self.assertEqual(restored['current'], initial['current'])
        self.assertEqual(len(restored['history']), 3)

    def test_tampered_report_or_artifact_refused(self):
        from ascendra.continuation_cycle import initialize_versions, promote_candidate
        registry = Path(self.temp.name) / 'registry'
        old = initialize_versions(registry, self.base)['current']
        report = self.report(); report['mean_gain'] = 1
        with self.assertRaises(ValueError):
            promote_candidate(registry, self.base, self.candidate, report, expected_current=old, allow_promotion=True)
        report = self.report(); (self.candidate / 'code.py').write_text('changed')
        with self.assertRaises(ValueError):
            promote_candidate(registry, self.base, self.candidate, report, expected_current=old, allow_promotion=True)

    def test_concurrent_promotion_only_one_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from ascendra.continuation_cycle import initialize_versions, promote_candidate
        registry = Path(self.temp.name) / 'registry'
        old = initialize_versions(registry, self.base)['current']; report = self.report()
        def attempt(_):
            try:
                promote_candidate(registry, self.base, self.candidate, report, expected_current=old, allow_promotion=True)
                return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(attempt, range(2))), 1)

    def test_script_evaluator_executes_operator_script(self):
        from ascendra.evaluation_cli import script_evaluator
        import sys
        executable = Path(self.temp.name) / 'trusted.py'
        executable.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\nr=json.load(sys.stdin)\nscore=.9 if (Path(r["artifact"])/"code.py").read_text()=="new" else .5\nprint(json.dumps({"score":score,"cost":0,"seconds":0}))\n')
        executable.chmod(0o700)
        evaluator, digest = script_evaluator(executable)
        report = self.evaluate(evaluator, repeats=2)
        self.assertEqual(report['status'], 'eligible')
        self.assertEqual(len(digest), 64)
        executable.write_text('changed')
        with self.assertRaises(ValueError): evaluator(self.base, 'a', {'max_seconds': 2}, 0)


if __name__ == '__main__': unittest.main()
