import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ascendra.execution_bridge import (
    ExecutionBridge, FenceLost, LocalRunner, SitesTransport, bounded_artifact,
)


class Clock:
    def __init__(self):
        self.now = 1000
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Process:
    def __init__(self, clock, duration=10):
        self.clock, self.end = clock, clock() + duration
    def poll(self):
        return 0 if self.clock() >= self.end else None


class Runner:
    def __init__(self, clock):
        self.clock, self.cancelled, self.starts = clock, [], 0
    def prepare(self, job):
        return 'same-local-job'
    def start(self, local_id):
        self.starts += 1
        return Process(self.clock)
    def progress(self, local_id):
        return {'state': 'running'}
    def cancel(self, local_id):
        self.cancelled.append(local_id)
    def result(self, local_id):
        return {'status': 'completed', 'result': {'report': {'passed': True}}}


class Transport:
    def __init__(self, clock):
        self.clock, self.calls, self.heartbeats, self.sequence = clock, [], 0, 4
        self.lose, self.outage = False, False
    def __call__(self, action, data):
        self.calls.append((action, data))
        if action == 'claim':
            return {'job': {'id': 'remote-1', 'lease_token': 'fence',
                           'lease_expires_at': (self.clock() + 60) * 1000,
                           'checkpoint_seq': self.sequence}}
        if action == 'heartbeat':
            self.heartbeats += 1
            if self.outage and self.heartbeats > 1:
                raise OSError('connection lost')
            return {'accepted': not (self.lose and self.heartbeats > 1),
                    'lease_expires_at': (self.clock() + 60) * 1000}
        if action == 'checkpoint':
            assert data['expected_seq'] == self.sequence
            self.sequence += 1
            return {'accepted': True, 'checkpoint_seq': self.sequence}
        return {'accepted': True}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.runner = Runner(self.clock)
        self.remote = Transport(self.clock)
        self.terminated = []
        self.bridge = ExecutionBridge(self.remote, self.runner, clock=self.clock,
            sleep=self.clock.sleep, terminate=self.terminated.append)

    def test_completed_upload_requires_final_heartbeat(self):
        self.assertEqual(self.bridge.run_once(), 'completed')
        actions = [a for a, _ in self.remote.calls]
        self.assertEqual(actions[-1], 'result')
        self.assertGreaterEqual(self.remote.heartbeats, 2)
        self.assertFalse(self.runner.cancelled)
        self.assertEqual(self.remote.sequence, 5)

    def test_fence_loss_cancels_and_never_uploads(self):
        self.remote.lose = True
        with self.assertRaises(FenceLost):
            self.bridge.run_once()
        self.assertEqual(self.runner.cancelled, ['same-local-job'])
        self.assertEqual(len(self.terminated), 1)
        self.assertNotIn('result', [a for a, _ in self.remote.calls])

    def test_unknown_heartbeat_does_not_extend_deadline(self):
        self.remote.outage = True
        self.runner.start = lambda _: Process(self.clock, 500)
        with self.assertRaises(FenceLost):
            self.bridge.run_once()
        self.assertLess(self.clock(), 1060)
        self.assertTrue(self.runner.cancelled)
        self.assertNotIn('result', [a for a, _ in self.remote.calls])

    def test_recovery_waits_for_local_lease_instead_of_false_completion(self):
        count = [0]
        def start(_):
            count[0] += 1
            return Process(self.clock, 0 if count[0] == 1 else 10)
        self.runner.start = start
        self.runner.finished = lambda _: count[0] >= 2
        self.assertEqual(self.bridge.run_once(), 'completed')
        self.assertEqual(count[0], 2)

    def test_followup_runs_on_separate_lease_and_uploads_batch(self):
        calls = []
        def remote(action, data):
            calls.append((action, data))
            if action == 'followup-claim':
                return {'followup': {'id': 'parent', 'lease_token': 'research-fence',
                    'lease_expires_at': 1180000, 'deadline_at': 1180000}}
            return {'accepted': True}
        self.bridge.transport = remote
        self.runner.prepare_followup = lambda remote: 'child'
        self.runner.start_followup = lambda child: Process(self.clock, 5)
        self.runner.followup_result = lambda child: {'status': 'completed', 'batch': {'id': 'batch'}}
        self.runner.cancel_followup = lambda child: self.fail('should not cancel')
        self.assertEqual(self.bridge.run_followup_once(), 'completed')
        self.assertEqual(calls[0][0], 'followup-claim')
        self.assertIn('followup-heartbeat', [a for a, _ in calls])
        self.assertEqual(calls[-1][0], 'followup-result')
        self.assertEqual(calls[-1][1]['batch']['id'], 'batch')

    def test_followup_timeout_stops_without_uploading_late_result(self):
        calls, cancelled = [], []
        def remote(action, data):
            calls.append(action)
            return {'followup': {'id': 'parent', 'lease_token': 'research-fence',
                'lease_expires_at': 1010000, 'deadline_at': 1010000}}
        self.bridge.transport = remote
        self.runner.prepare_followup = lambda remote: 'child'
        self.runner.start_followup = lambda child: Process(self.clock, 100)
        self.runner.cancel_followup = cancelled.append
        with self.assertRaises(FenceLost):
            self.bridge.run_followup_once()
        self.assertEqual(cancelled, ['child'])
        self.assertEqual(calls, ['followup-claim'])
        self.assertEqual(len(self.terminated), 1)

    def test_followup_remote_stop_cancels_child(self):
        calls, cancelled = [], []
        def remote(action, data):
            calls.append(action)
            if action == 'followup-claim':
                return {'followup': {'id': 'parent', 'lease_token': 'research-fence',
                    'lease_expires_at': 1180000, 'deadline_at': 1180000}}
            return {'accepted': False, 'stop_requested': True}
        self.bridge.transport = remote
        self.runner.prepare_followup = lambda remote: 'child'
        self.runner.start_followup = lambda child: Process(self.clock, 100)
        self.runner.cancel_followup = cancelled.append
        with self.assertRaises(FenceLost):
            self.bridge.run_followup_once()
        self.assertEqual(cancelled, ['child'])
        self.assertNotIn('followup-result', calls)

    def test_reject_credential_redirect_origins(self):
        for origin in ('http://x.chatgpt.site', 'https://evil.test',
                       'https://x.chatgpt.site/path', 'https://u@x.chatgpt.site',
                       'https://x.chatgpt.site:443', 'https://x.chatgpt.site?x=1'):
            with self.assertRaises(ValueError):
                SitesTransport(origin, 'secret1', 'secret2')

    def test_artifact_bounds_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / 'candidate'
            artifact.mkdir()
            (artifact / 'index.html').write_text('<html></html>')
            self.assertEqual(bounded_artifact(artifact, root)[0]['path'], 'index.html')
            (artifact / 'app.js').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):
                bounded_artifact(artifact, root)

    def test_missing_recovery_storage_does_not_regenerate(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = LocalRunner(temp)
            with self.assertRaisesRegex(ValueError, 'Recovery storage'):
                runner.prepare({'id': 'remote', 'checkpoint': {'local_id': 'old'}})

    def test_local_prepare_reuses_identical_durable_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            job = {'id': 'remote-one', 'snapshot': {'kind': 'brief', 'mode': 'project',
                'brief': {'title': 'Demo', 'description': 'Create static page'},
                'verification_level': 'smoke'}, 'budget': {'max_calls': 4,
                'max_repairs': 3, 'max_seconds': 600, 'max_tokens': 60000, 'max_agents': 2}}
            first = LocalRunner(temp)
            local_id = first.prepare(job)
            job['checkpoint'] = {'local_id': local_id}
            second = LocalRunner(temp)
            self.assertEqual(second.prepare(job), local_id)
            queue, _, _ = second.jobs[local_id]
            self.assertEqual(len(queue.list_jobs()), 1)
            self.assertEqual(queue.get(local_id)['payload']['provider']['model'], 'qwen2.5-coder:7b')

    def test_result_binds_uploaded_files_to_verified_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            from ascendra.execution_queue import ExecutionQueue
            root = Path(temp)
            artifact = root / 'candidate'
            artifact.mkdir()
            (artifact / 'index.html').write_text('<html>done</html>')
            hashes = {'index.html': hashlib.sha256(b'<html>done</html>').hexdigest()}
            queue = ExecutionQueue(root / 'execution.sqlite3')
            local = queue.enqueue('sites_bridge', 'key', {})
            claimed = queue.claim('worker')
            queue.finish(local['id'], 'worker', claimed['fence'], result={
                'status': 'verified', 'artifact': str(artifact), 'attempts': [{
                    'status': 'verified', 'files': hashes,
                    'verification': {'passed': True, 'checks': [{'name': 'check', 'passed': True}]}}]})
            runner = LocalRunner(temp)
            runner.jobs[local['id']] = (queue, root, {'snapshot': {'verification_level': 'smoke'}})
            output = runner.result(local['id'])
            self.assertEqual(output['result']['artifact_sha256'], hashes)
            (artifact / 'index.html').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'changed since verification'):
                runner.result(local['id'])


if __name__ == '__main__':
    unittest.main()
