import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from ascendra.capability_autonomy import copy_public_project, run_autonomous, _history_context
from ascendra.v4_ledger import FileLedger


class FakeDecider:
    def __init__(self, output, *, model, effort, max_calls, writable_paths):
        self.output = Path(output)
        self.calls = 0
        self.ledger = FileLedger(self.output/'ledger', 'fake', dict(calls=max_calls,
            phase_caps={'planning':max_calls}, tokens=1000, wall_seconds=60))

    def __call__(self, request, schema):
        self.calls += 1
        def invoke(_):
            if 'capacity' in request:
                tasks = [dict(title='worker '+str(i), goal='Change value independently')
                         for i in range(min(2, request['capacity']))]
                response = dict(rationale='Independent parallel changes', done=False, tasks=tasks)
            else:
                worker = self.output.parent
                (worker/'started').write_text(str(time.monotonic()))
                round_output = worker.parent
                limit = time.monotonic()+2
                # Real child processes must overlap, not merely be scheduled sequentially.
                while len(list(round_output.glob('worker-*/started'))) < 2:
                    if time.monotonic() > limit:
                        raise RuntimeError('Workers did not overlap')
                    time.sleep(.01)
                response = dict(action='tool' if self.calls==1 else 'finish',
                    tool='write_file' if self.calls==1 else None,
                    arguments_json=json.dumps(dict(path='value.py', content='VALUE = 2\n')) if self.calls==1 else None,
                    proposal_json=None, message='Observed actual change' if self.calls>1 else None)
            return response, dict(total_tokens=1)
        return self.ledger.execute(str(self.calls), dict(phase='planning', reserved_tokens=1), invoke)[0]


class DoneDecider(FakeDecider):
    def __call__(self, request, schema):
        return dict(rationale='No useful task', done=True, tasks=[])


class TooManyDecider(FakeDecider):
    def __call__(self, request, schema):
        return dict(rationale='Invalid oversubscription', done=False,
                    tasks=[dict(title='x', goal='y')]*33)


class SlowDecider(FakeDecider):
    def __call__(self, request, schema):
        root = self.output.parents[2]
        def invoke(_):
            marker = root/'escaped-child'
            subprocess.Popen([sys.executable, '-c',
                "import time,pathlib; time.sleep(.5); pathlib.Path("+repr(str(marker))+").write_text('bad')"])
            (root/'slow-started').touch()
            time.sleep(10)
            return {}, dict(total_tokens=1)
        return self.ledger.execute('slow', dict(phase='planning', reserved_tokens=1), invoke)[0]


class DecisionFailure(FakeDecider):
    def __call__(self, request, schema):
        if 'capacity' in request:
            return dict(rationale='test', done=False, tasks=[dict(title='fails', goal='fail')])
        raise RuntimeError('provider unavailable')


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root/'project'
        self.project.mkdir()
        (self.project/'value.py').write_text('VALUE = 1\n')
        self.output = self.root/'run'

    def args(self, **kwargs):
        values = dict(project=str(self.project), output=str(self.output), mission='Investigate',
            max_agents=2, max_calls=5, minutes=1, max_steps=2, allow_write=['value.py'],
            model='fake', effort='low')
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_parallel_budget_isolation_and_real_findings(self):
        result = run_autonomous(self.args(), decider_factory=FakeDecider, poll_interval=.01)
        self.assertEqual(result['state'], 'budget_exhausted')
        self.assertEqual(result['reserved_calls'], 5)
        self.assertEqual(result['usage']['calls'], 5)
        self.assertEqual(result['completed_tasks'], 2)
        self.assertEqual((self.project/'value.py').read_text(), 'VALUE = 1\n')
        workers = result['rounds'][0]['findings']
        self.assertEqual(len(workers), 2)
        for worker in workers:
            self.assertEqual(worker['findings']['finish_message'], 'Observed actual change')
            self.assertEqual(worker['changes'][0]['path'], 'value.py')
            self.assertIsNone(worker['objective_success'])
        from ascendra.capability_memory import ExperienceStore
        self.assertEqual(ExperienceStore(self.output/'memory').context()['episodes'], 2)
        config = json.loads((self.output/'configuration.json').read_text())
        self.assertEqual(config['mode'], 'autonomous')

    def test_snapshot_excludes_private_symlink_and_hardlink(self):
        (self.project/'.env').write_text('secret')
        (self.project/'.git').mkdir()
        (self.project/'.git'/'config').write_text('secret')
        (self.project/'link').symlink_to(self.project/'value.py')
        import os
        os.link(self.project/'value.py', self.project/'hardlink')
        (self.project/'public.txt').write_text('public')
        manifest = copy_public_project(self.project, self.root/'copy')
        self.assertEqual(set(manifest), {'public.txt'})
        self.assertEqual(manifest['public.txt'], hashlib.sha256(b'public').hexdigest())

    def test_done_creates_no_workers(self):
        result = run_autonomous(self.args(), decider_factory=DoneDecider, poll_interval=.01)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['reserved_calls'], 1)
        self.assertEqual(result['agents'], [])

    def test_plan_cannot_exceed_agent_limit(self):
        result = run_autonomous(self.args(), decider_factory=TooManyDecider, poll_interval=.01)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['reserved_calls'], 1)
        self.assertEqual(result['agents'], [])

    def test_stop_kills_coordinator_and_descendant_and_retains_usage(self):
        def stopper():
            limit=time.monotonic()+3
            while not (self.output/'slow-started').exists() and time.monotonic()<limit:
                time.sleep(.01)
            (self.output/'STOP').touch()
        thread = threading.Thread(target=stopper)
        thread.start()
        started=time.monotonic()
        result = run_autonomous(self.args(), decider_factory=SlowDecider, poll_interval=.01)
        thread.join(timeout=3)
        self.assertLess(time.monotonic()-started, 2)
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(result['reserved_calls'], 1)
        self.assertEqual(result['usage']['calls'], 1)
        self.assertEqual(result['usage']['unknown_usage_calls'], 1)
        time.sleep(.6)
        self.assertFalse((self.output/'escaped-child').exists())

    def test_deadline_interrupts_provider(self):
        started=time.monotonic()
        result = run_autonomous(self.args(minutes=.003), decider_factory=SlowDecider, poll_interval=.01)
        self.assertEqual(result['state'], 'deadline')
        self.assertLess(time.monotonic()-started, 2)

    def test_decision_error_is_not_completed_task(self):
        result = run_autonomous(self.args(max_calls=3), decider_factory=DecisionFailure, poll_interval=.01)
        self.assertEqual(result['completed_tasks'], 0)
        self.assertEqual(result['rounds'][0]['findings'][0]['state'], 'failed')
        self.assertEqual(result['rounds'][0]['findings'][0]['summary']['stop_reason'], 'decision_error')

    def test_adaptation_context_preserves_every_recent_worker(self):
        history=[]
        for number in range(4):
            history.append(dict(round=number, plan=dict(rationale='why'*3000), findings=[
                dict(agent=f'{number}-{index}', state='completed', summary=dict(stop_reason='finished'),
                     findings=dict(finish_message='x'*16000, observations=[{'result':'x'*12000}]),
                     changes=[dict(path='value.py', patch='y'*12000)]) for index in range(32)]))
        context=_history_context(history)
        self.assertEqual([item['round'] for item in context], [1,2,3])
        self.assertEqual([len(item['findings']) for item in context], [32,32,32])
        self.assertEqual(context[-1]['findings'][-1]['agent'], '3-31')
        self.assertLess(len(json.dumps(context)), 60000)

    def test_output_and_write_scope_rejected_before_start(self):
        with self.assertRaises(ValueError):
            run_autonomous(self.args(output=str(self.project/'run')), decider_factory=FakeDecider)
        with self.assertRaises(ValueError):
            run_autonomous(self.args(allow_write=['../outside']), decider_factory=FakeDecider)
        self.assertFalse(self.output.exists())


if __name__=='__main__':
    unittest.main()
