from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from ascendra.execution_queue import ExecutionQueue, LeaseLost


class ExecutionQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.db'
        self.now = 1000.
        self.queue = ExecutionQueue(self.path, clock=lambda: self.now)

    def enqueue(self):
        return self.queue.enqueue('owner', 'approved-1', {'description': 'Make an app'})

    def test_concurrent_idempotency_and_ownership(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: self.enqueue(), range(20)))
        self.assertEqual(len({j['id'] for j in jobs}), 1)
        with self.assertRaises(ValueError):
            self.queue.enqueue('owner', 'approved-1', {'description': 'changed'})
        other = self.queue.enqueue('another-owner', 'approved-1', {})
        self.assertNotEqual(other['id'], jobs[0]['id'])
        with self.assertRaises(KeyError):
            self.queue.get(jobs[0]['id'], owner_id='another-owner')

    def test_concurrent_claim_single_winner(self):
        self.enqueue()
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda n: self.queue.claim(f'worker-{n}'), range(20)))
        self.assertEqual(sum(j is not None for j in claims), 1)

    def test_restart_reclaim_preserves_checkpoint_and_fences_old_worker(self):
        self.enqueue()
        first = self.queue.claim('worker', lease_seconds=10)
        self.queue.checkpoint(first['id'], 'worker', first['fence'], 'plan', {'artifact': 'sha256'})
        self.now += 10
        restarted = ExecutionQueue(self.path, clock=lambda: self.now)
        second = restarted.claim('worker', lease_seconds=10)
        self.assertEqual(second['checkpoints'], {'plan': {'artifact': 'sha256'}})
        self.assertGreater(second['fence'], first['fence'])
        for operation in [lambda: self.queue.heartbeat(first['id'], 'worker', first['fence']),
                          lambda: self.queue.checkpoint(first['id'], 'worker', first['fence'], 'build', {}),
                          lambda: self.queue.finish(first['id'], 'worker', first['fence'])]:
            with self.assertRaises(LeaseLost):
                operation()
        restarted.finish(second['id'], 'worker', second['fence'], result={'tested': False})
        self.assertIsNone(restarted.claim('third-worker'))

    def test_expired_lease_cannot_renew_even_before_reclaim(self):
        self.enqueue()
        job = self.queue.claim('worker', lease_seconds=1)
        self.now += 1
        with self.assertRaises(LeaseLost):
            self.queue.heartbeat(job['id'], 'worker', job['fence'])

    def test_heartbeat_and_immutable_checkpoints(self):
        self.enqueue()
        job = self.queue.claim('worker', lease_seconds=10)
        self.now += 9
        self.queue.heartbeat(job['id'], 'worker', job['fence'], lease_seconds=20)
        self.now += 2
        self.assertIsNone(self.queue.claim('other'))
        self.queue.checkpoint(job['id'], 'worker', job['fence'], 'plan', {'ok': True})
        self.queue.checkpoint(job['id'], 'worker', job['fence'], 'plan', {'ok': True})
        with self.assertRaises(ValueError):
            self.queue.checkpoint(job['id'], 'worker', job['fence'], 'plan', {'ok': False})

    def test_cancellation_revokes_worker_and_is_owner_scoped(self):
        self.enqueue()
        job = self.queue.claim('worker')
        with self.assertRaises(KeyError):
            self.queue.cancel(job['id'], 'intruder')
        self.assertEqual(self.queue.cancel(job['id'], 'owner')['state'], 'cancelled')
        with self.assertRaises(LeaseLost):
            self.queue.finish(job['id'], 'worker', job['fence'])
        self.now += 1000
        self.assertIsNone(self.queue.claim('other'))
        self.assertEqual(self.queue.cancel(job['id'], 'owner')['state'], 'cancelled')

    def test_queued_cancel_and_failure_terminal(self):
        job = self.enqueue()
        self.queue.cancel(job['id'], 'owner')
        self.assertIsNone(self.queue.claim('worker'))
        self.queue.enqueue('owner', 'second', {})
        claimed = self.queue.claim('worker')
        failed = self.queue.finish(claimed['id'], 'worker', claimed['fence'], state='failed', result={'reason': 'budget'})
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(self.queue.cancel(claimed['id'], 'owner')['state'], 'failed')
        self.assertIsNone(self.queue.claim('worker'))


if __name__ == '__main__':
    unittest.main()
