from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from ascendra.continuation_worker import schedule_after_run, process_one
from ascendra.execution_queue import ExecutionQueue


def evidence(topic, **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    return {'id': 'research_test', 'topic': topic, 'status': 'complete',
            'researched_at': now, 'errors': [], 'sources': [{'url': 'https://example.org/docs',
                'title': 'Docs', 'excerpt': 'Testing methods', 'retrieved_at': now}]}


def factory(*args, **kwargs):
    assert kwargs['max_calls'] == 1
    assert kwargs['max_output_tokens'] == 2048
    def decide(request, schema):
        return {'proposals': [{'id': str(i), 'title': 'Proposal ' + str(i),
            'description': 'Distinct implementation ' + str(i), 'benefit': 'Measured improvement',
            'estimated_effort': 'One day', 'risks': ['May regress'],
            'acceptance_criteria': ['Independent before/after checks', 'Zero regression in existing cases'],
            'source_urls': ['https://example.org/docs']} for i in range(3)],
            'recommended_id': '0', 'recommendation_reason': 'Smallest change'}
    return decide


class ContinuationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.queue = ExecutionQueue(self.data / 'continuation.sqlite3')
        self.parent = {'id': 'parent', 'owner_id': 'owner', 'state': 'completed', 'result': {'status': 'verified'}}

    def schedule(self):
        return schedule_after_run(self.queue, self.parent, 'Next improvement', enabled=True)

    def test_optin_verified_parent_and_deduplication(self):
        self.assertIsNone(schedule_after_run(self.queue, self.parent, 'next'))
        first = self.schedule(); self.assertEqual(first['id'], self.schedule()['id'])
        with self.assertRaises(ValueError):
            schedule_after_run(self.queue, {**self.parent, 'state': 'failed'}, 'next', enabled=True)

    def test_worker_persists_batch_awaiting_selection(self):
        child = self.schedule()
        result = process_one(self.data, research_fn=evidence, decider_factory=factory)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['status'], 'awaiting_selection')
        self.assertEqual(len(result['result']['batch']['proposals']), 3)
        self.assertFalse(result['result']['execution_started'])
        self.assertIn('model_reserved', self.queue.get(child['id'])['checkpoints'])
        self.assertIsNone(process_one(self.data, research_fn=evidence, decider_factory=factory))

    def test_remaining_budget_and_concise_schema(self):
        self.schedule()
        captured = {}
        def bounded_factory(*args, **kwargs):
            captured.update(kwargs)
            delegate = factory(*args, **kwargs)
            def decide(request, schema):
                self.assertIn('EXACTLY 3', request['instructions'])
                proposals = schema['properties']['proposals']
                self.assertEqual(proposals['maxItems'], 3)
                fields = proposals['items']['properties']
                self.assertEqual(fields['risks']['maxItems'], 1)
                self.assertEqual(fields['acceptance_criteria']['maxItems'], 2)
                self.assertEqual(fields['source_urls']['items']['enum'], ['https://example.org/docs'])
                return delegate(request, schema)
            return decide
        result = process_one(self.data, research_fn=evidence, decider_factory=bounded_factory)
        self.assertEqual(result['state'], 'completed')
        self.assertGreater(captured['timeout_s'], 170)
        self.assertLessEqual(captured['timeout_s'], 177)
        self.assertEqual(result['result']['batch']['mode'], 'project')

    def test_failure_durable_no_retry(self):
        child = self.schedule()
        def broken(*args, **kwargs): raise RuntimeError('private failure detail')
        result = process_one(self.data, research_fn=evidence, decider_factory=broken)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['result']['error_type'], 'RuntimeError')
        self.assertNotIn('private', str(result['result']))
        self.assertEqual(self.schedule()['id'], child['id'])
        self.assertIsNone(process_one(self.data, research_fn=evidence, decider_factory=factory))

    def test_interrupted_reserved_call_never_replays(self):
        child = self.schedule()
        old = ExecutionQueue(self.data / 'continuation.sqlite3', clock=lambda: 1)
        claim = old.claim('oldworker', lease_seconds=1)
        old.checkpoint(child['id'], 'oldworker', claim['fence'], 'model_reserved', {'calls': 1})
        def forbidden(*args, **kwargs): self.fail('must not replay')
        result = process_one(self.data, research_fn=forbidden, decider_factory=forbidden)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['result']['status'], 'interrupted_uncertain')


if __name__ == '__main__': unittest.main()
