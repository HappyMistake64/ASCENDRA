import argparse
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascendra.studio_cli import execute_job, parser
from ascendra.studio_store import StudioStore


class StudioIntegrationTests(unittest.TestCase):
    def setup_job(self, root, mode='project'):
        store = StudioStore(root / 'studio.sqlite3')
        now = datetime.now(timezone.utc).isoformat()
        store.save_research({'id': 'r1', 'topic': 'Apps', 'status': 'complete',
                             'researched_at': now, 'sources': [{
                                 'url': 'https://docs.python.org/3/', 'title': 'Python',
                                 'excerpt': 'Documentation', 'retrieved_at': now}], 'errors': []})
        store.save_batch({'id': 'b1', 'research_id': 'r1', 'mode': mode,
                          'recommended_id': 'p0', 'recommendation_reason': 'Smallest useful change',
                          'proposals': [{'id': f'p{i}', 'title': f'Idea {i}',
                                         'description': f'Implement isolated feature {i}',
                                         'benefit': 'Improved reliability', 'estimated_effort': '1 hour',
                                         'risks': ['Requires testing'],
                                         'acceptance_criteria': ['Independent checks pass'],
                                         'source_urls': ['https://docs.python.org/3/']}
                                        for i in range(3)]})
        return store, store.approve('b1', 'p0', max_calls=2)

    def args(self, root, job):
        return argparse.Namespace(data=root, job_id=job['id'], project=None,
                                  allow_write=[], model='test')

    def test_approved_project_executes_once_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, job = self.setup_job(root)
            args = self.args(root, job)
            calls = []
            def factory(args, output, budget, paths):
                calls.append(budget)
                return lambda request, schema: {}
            with patch('ascendra.studio_projects.build_project', return_value={'status': 'built'}) as build:
                result = execute_job(args, store, decider_factory=factory)
                self.assertEqual(result['state'], 'completed')
                self.assertFalse(result['verified_improvement'])
                self.assertEqual(calls, [2])
                build.assert_called_once()
                with self.assertRaises(ValueError):
                    execute_job(args, store, decider_factory=factory)
            self.assertEqual(StudioStore(root / 'studio.sqlite3').get_job(job['id'])['state'], 'completed')

    def test_provider_failure_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, job = self.setup_job(root)
            def unavailable(*args):
                raise RuntimeError('provider unavailable')
            with self.assertRaises(RuntimeError):
                execute_job(self.args(root, job), store, decider_factory=unavailable)
            self.assertEqual(store.get_job(job['id'])['state'], 'failed')

    def test_self_improvement_requires_write_scope_before_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, job = self.setup_job(root, 'self_improvement')
            with self.assertRaises(ValueError):
                execute_job(self.args(root, job), store)
            self.assertEqual(store.get_job(job['id'])['state'], 'queued')

    def test_cli_defaults(self):
        args = parser().parse_args(['--data', '/tmp/studio', 'propose', 'useful app'])
        self.assertEqual(args.mode, 'project')


if __name__ == '__main__':
    unittest.main()
