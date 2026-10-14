from pathlib import Path
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ascendra.execution_cli import enqueue, execute_claim, run_process, StopRequested
from ascendra.execution_queue import ExecutionQueue


CONTRACT = {'version': 1, 'scenarios': [{'name': 'Required task form', 'steps': [
    {'action': 'expect_visible', 'selector': '#task'}]}]}


class Crash(BaseException):
    pass


class ExecutionCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = time.time()
        self.queue = ExecutionQueue(self.root / 'execution.sqlite3', clock=lambda: self.clock)
        self.calls = []
        sandbox = patch('ascendra.execution_cli.build_command',
            side_effect=lambda project, contract, output: ['node', 'browser_verify.mjs', str(project), str(contract), str(output)])
        sandbox.start()
        self.addCleanup(sandbox.stop)

    def add(self, **options):
        return enqueue(self.queue, owner='owner', key='approved', description='Task form',
                       contract=CONTRACT, **options)

    def runner(self, argv, *, timeout_s, log_path, pulse):
        pulse()
        self.calls.append(argv)
        if '_generate' in argv:
            request = json.loads(Path(argv[argv.index('--request') + 1]).read_text())
            path = Path(argv[argv.index('--destination') + 1])
            path.mkdir()
            (path / 'index.html').write_text('<html><head></head><body><input id="task"></body></html>')
            if 'repair' in request:
                self.assertIn('index.html', request['repair']['files'])
                self.assertFalse(request['repair']['verification']['passed'])
                self.assertEqual(request['contract'], CONTRACT)
        else:
            Path(argv[-1]).write_text(json.dumps({'passed': True, 'checks': [
                {'scenario': 'Required task form', 'action': 'expect_visible', 'passed': True}],
                'page_errors': []}))
        return 0

    def test_complete_and_idempotent_enqueue(self):
        job = self.add()
        self.assertEqual(self.add()['id'], job['id'])
        result = execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'verified')
        self.assertTrue(Path(result['artifact'], 'index.html').is_file())
        self.assertFalse(result['published'])
        saved = self.queue.get(job['id'])
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(set(saved['checkpoints']), {'started', 'call-000', 'generated-000', 'tested-000-000', 'tested-000'})
        self.assertEqual(len(self.calls), 2)

    def test_repair_uses_prior_source_and_real_failed_evidence(self):
        self.add()
        def runner(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[0] == 'node' and 'candidate-000' in argv[-3]:
                Path(argv[-1]).write_text(json.dumps({'passed': False, 'checks': [
                    {'scenario': 'Required task form', 'passed': False, 'error': 'Missing input'}]}))
                return 1
            return result
        result = execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=runner)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['model_calls'], 2)
        self.assertEqual(len(result['attempts']), 2)

    def test_budget_failure_never_claims_verification(self):
        self.add(max_calls=1)
        def runner(argv, **kwargs):
            code = self.runner(argv, **kwargs)
            if argv[0] == 'node':
                Path(argv[-1]).write_text(json.dumps({'passed': False, 'checks': [{'passed': False}]}))
                return 1
            return code
        job = self.queue.claim('worker')
        result = execute_claim(self.queue, job, self.root, process_runner=runner)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'model_call_budget_exhausted')
        self.assertIsNone(result['artifact'])
        self.assertEqual(self.queue.get(job['id'])['state'], 'failed')

    def test_generated_checkpoint_resumes_without_second_inference(self):
        self.add()
        def crash_verifier(argv, **kwargs):
            if argv[0] == 'node':
                raise Crash()
            return self.runner(argv, **kwargs)
        with self.assertRaises(Crash):
            execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=crash_verifier)
        self.clock += 61
        claimed = self.queue.claim('new-worker')
        result = execute_claim(self.queue, claimed, self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(sum('_generate' in argv for argv in self.calls), 1)
        self.assertIn('fence-2', result['artifact'])

    def test_inflight_model_call_not_replayed_after_crash(self):
        self.add()
        def crash(argv, **kwargs):
            self.calls.append(argv)
            raise Crash()
        with self.assertRaises(Crash):
            execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=crash)
        self.clock += 61
        result = execute_claim(self.queue, self.queue.claim('worker2'), self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error_type'], 'UncertainModelCall')
        self.assertEqual(len(self.calls), 1)

    def test_cancellation_during_work_preserves_cancelled_state(self):
        job = self.add()
        def cancel(argv, **kwargs):
            self.queue.cancel(job['id'], 'owner')
            kwargs['pulse']()
        result = execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.queue.get(job['id'])['state'], 'cancelled')

    def test_worker_stop_leaves_lease_for_recovery(self):
        job = self.add()
        stop = threading.Event()
        def stopped(argv, **kwargs):
            stop.set()
            kwargs['pulse']()
        result = execute_claim(self.queue, self.queue.claim('worker'), self.root, stop=stop, process_runner=stopped)
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(self.queue.get(job['id'])['state'], 'running')

    def test_contract_required_and_assertions_required(self):
        for contract in ({}, {'version': 1, 'scenarios': [{'name': 'No assertions', 'steps': [{'action': 'reload'}]}]}):
            with self.assertRaises(ValueError):
                enqueue(self.queue, owner='owner', key='bad', description='App', contract=contract)
        self.assertEqual(self.queue.list_jobs(), [])

    def test_persistent_deadline_not_reset_on_reclaim(self):
        self.add()
        job = self.queue.claim('worker')
        self.queue.checkpoint(job['id'], 'worker', job['fence'], 'started', {'at': time.time()-100, 'deadline': time.time()-1})
        self.clock += 61
        result = execute_claim(self.queue, self.queue.claim('worker2'), self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error_type'], 'TimeoutError')
        self.assertEqual(self.calls, [])

    def test_tokens_cap_calls_and_parallel_scenario_workers_are_real(self):
        contract = {'version': 1, 'scenarios': [
            {'name': 'scenario-' + str(i), 'steps': [{'action': 'expect_visible', 'selector': '#task'}]}
            for i in range(2)]}
        job = enqueue(self.queue, owner='owner', key='approved', description='Form',
                      contract=contract, max_tokens=20480, max_calls=4, max_agents=2)
        self.assertEqual(job['payload']['limits']['max_model_calls'], 1)
        barrier = threading.Barrier(2, timeout=3)
        lock = threading.Lock()
        active = 0
        peak = 0
        def runner(argv, **kwargs):
            nonlocal active, peak
            if argv[0] == 'node':
                with lock:
                    active += 1
                    peak = max(active, peak)
                barrier.wait()
                try:
                    return self.runner(argv, **kwargs)
                finally:
                    with lock:
                        active -= 1
            return self.runner(argv, **kwargs)
        result = execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=runner)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(peak, 2)
        self.assertEqual(result['attempts'][0]['verification']['verification_workers'], 2)
        self.assertEqual(sum('_generate' in argv for argv in self.calls), 1)
        with self.assertRaises(ValueError):
            self.add(max_tokens=20479)

    def test_changed_checkpoint_artifact_is_rejected_on_restart(self):
        self.add()
        def crash_verifier(argv, **kwargs):
            if argv[0] == 'node':
                raise Crash()
            return self.runner(argv, **kwargs)
        first = self.queue.claim('worker')
        with self.assertRaises(Crash):
            execute_claim(self.queue, first, self.root, process_runner=crash_verifier)
        point = self.queue.get(first['id'])['checkpoints']['generated-000']
        Path(point['path'], 'index.html').write_text('modified after checkpoint')
        self.clock += 61
        result = execute_claim(self.queue, self.queue.claim('worker2'), self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.calls), 1)

    def test_planned_strategy_dispatches_real_builders_and_selects_passing_candidate(self):
        self.add(strategy='planned', max_agents=2, max_calls=3)
        builder_barrier = threading.Barrier(2, timeout=3)
        def runner(argv, **kwargs):
            if '_plan' in argv:
                self.calls.append(argv)
                output = Path(argv[argv.index('--destination') + 1])
                output.write_text(json.dumps({'approaches': [
                    {'id': 'a', 'role': 'builder', 'approach': 'Use a plain form with native controls', 'depends_on': []},
                    {'id': 'b', 'role': 'builder', 'approach': 'Use a compact accessible task list', 'depends_on': []}]}))
                return 0
            if '_generate' in argv:
                request = json.loads(Path(argv[argv.index('--request') + 1]).read_text())
                self.assertEqual(request['max_calls'], 1)
                self.assertIn('approach', request)
                builder_barrier.wait()
            result = self.runner(argv, **kwargs)
            if argv[0] == 'node' and '/builders/a/' in argv[-3]:
                Path(argv[-1]).write_text(json.dumps({'passed': False, 'checks': [{'passed': False}]}))
                return 1
            return result
        job = self.queue.claim('worker')
        result = execute_claim(self.queue, job, self.root, process_runner=runner)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['planning']['selected'], 'b')
        self.assertEqual(result['planning']['effective_workers'], 2)
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['reserved_tokens'], 61440)
        self.assertEqual(sum('_plan' in argv for argv in self.calls), 1)
        self.assertEqual(sum('_generate' in argv for argv in self.calls), 2)
        self.assertEqual(self.queue.get(job['id'])['state'], 'completed')

    def test_planned_crash_does_not_replay_planner(self):
        self.add(strategy='planned', max_calls=2)
        def crash(argv, **kwargs):
            self.calls.append(argv)
            raise Crash()
        with self.assertRaises(Crash):
            execute_claim(self.queue, self.queue.claim('worker'), self.root, process_runner=crash)
        self.clock += 61
        result = execute_claim(self.queue, self.queue.claim('worker2'), self.root, process_runner=self.runner)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error_type'], 'UncertainModelCall')
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(ValueError):
            self.add(strategy='planned', max_calls=1)

    def test_host_worker_cap_bounds_requested_parallelism(self):
        from ascendra.execution_cli import worker_limit
        with patch.dict(os.environ, {'ASCENDRA_MAX_WORKERS': '2'}):
            self.assertEqual(worker_limit(50), 2)
            self.assertEqual(worker_limit(1), 1)
        with patch.dict(os.environ, {'ASCENDRA_MAX_WORKERS': '0'}):
            with self.assertRaises(ValueError):
                worker_limit(5)

    def test_subprocess_timeout_and_stop_terminate_process_group(self):
        pidfile = self.root / 'child.pid'
        script = ('import os,time,pathlib; pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid())); time.sleep(30)')
        with self.assertRaises(TimeoutError):
            run_process([sys.executable, '-c', script], timeout_s=.3,
                        log_path=self.root / 'timeout.log', pulse=lambda: None)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        calls = 0
        def pulse():
            nonlocal calls
            calls += 1
            if calls > 2:
                raise StopRequested()
        with self.assertRaises(StopRequested):
            run_process([sys.executable, '-c', script], timeout_s=10,
                        log_path=self.root / 'stop.log', pulse=pulse)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == '__main__':
    unittest.main()
