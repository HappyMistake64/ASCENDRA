from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from ascendra import capability_cli as cli


class AutonomousCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root/'run'
        self.run.mkdir()
        (self.run/'configuration.json').write_text(json.dumps({'mode':'autonomous'}))

    def invoke(self, *arguments):
        captured = io.StringIO()
        with redirect_stdout(captured):
            cli.main(list(arguments))
        return captured.getvalue()

    def test_autonomous_dispatch_preserves_scope_and_limits(self):
        runtime = ModuleType('ascendra.capability_autonomy')
        runtime.run_autonomous = Mock()
        with patch.dict('sys.modules', {'ascendra.capability_autonomy':runtime}):
            self.invoke('autonomous','--project','/project','--output','/output',
                        '--mission','Investigate independently','--allow-write','a.py',
                        '--allow-write','b.py','--max-agents','3','--max-calls','17',
                        '--minutes','0.5','--max-steps','2')
        args = runtime.run_autonomous.call_args.args[0]
        self.assertEqual(args.allow_write,['a.py','b.py'])
        self.assertEqual((args.max_agents,args.max_calls,args.minutes,args.max_steps),(3,17,.5,2))
        self.assertEqual(args.mission,'Investigate independently')

    def test_invalid_budgets_fail_before_runtime_import(self):
        for option,value in (('--max-agents','0'),('--max-agents','17'),('--max-calls','0'),
                             ('--minutes','0'),('--minutes','nan'),('--minutes','inf'),
                             ('--max-steps','33')):
            with self.subTest(option=option,value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.invoke('autonomous','--project','/project','--output','/output',option,value)
                self.assertEqual(error.exception.code,2)

    def test_watch_once_shows_status_and_complete_recent_events(self):
        (self.run/'status.json').write_text(json.dumps({'state':'running','active_workers':2}))
        (self.run/'events.jsonl').write_text(
            '{"event":"worker_started","goal":"Inspect"}\ninvalid\n{"event":"incomplete"')
        output = json.loads(self.invoke('watch','--output',str(self.run),'--once'))
        self.assertEqual(output['status']['active_workers'],2)
        self.assertEqual(output['recent_events'],[{'event':'worker_started','goal':'Inspect'}])

    def test_watch_ctrl_c_does_not_stop_supervisor(self):
        with patch.object(cli.time,'sleep',side_effect=KeyboardInterrupt):
            output = self.invoke('watch','--output',str(self.run))
        self.assertIn('run continues',output)
        self.assertFalse((self.run/'STOP').exists())

    def test_watch_exits_on_completed_or_deadline_run(self):
        for state in ('completed','deadline','budget_exhausted','stopped','failed'):
            with self.subTest(state=state):
                (self.run/'status.json').write_text(json.dumps({'state':state}))
                with patch.object(cli.time,'sleep') as sleep:
                    self.invoke('watch','--output',str(self.run))
                sleep.assert_not_called()

    def test_live_watch_renders_worker_progress_without_terminal_controls(self):
        (self.run/'status.json').write_text(json.dumps({'state':'completed','round':1,
            'max_agents':4,'max_calls':60,'reserved_calls':9,'usage':{'calls':3},
            'agents':[{'id':'r1-w1','state':'completed','task':{'title':'Inspect\u001b[2J'},
                       'progress':{'step':2,'action':'tool','tool':'read_file'}}]}))
        output=self.invoke('watch','--output',str(self.run))
        self.assertIn('calls 3/60',output)
        self.assertIn('step 2 read_file',output)
        self.assertNotIn('\u001b',output)

    def test_stop_is_idempotent_and_requires_real_run(self):
        for _ in range(2):
            self.assertEqual(json.loads(self.invoke('stop','--output',str(self.run)))['event'],'stop_requested')
        self.assertTrue((self.run/'STOP').is_file())
        unmarked=self.root/'unmarked'
        unmarked.mkdir()
        with self.assertRaises((ValueError,FileNotFoundError)):
            self.invoke('stop','--output',str(unmarked))
        self.assertFalse((unmarked/'STOP').exists())
        missing=self.root/'missing'
        with self.assertRaises(FileNotFoundError):
            self.invoke('stop','--output',str(missing))
        self.assertFalse(missing.exists())

    def test_stop_does_not_follow_existing_symlink(self):
        unrelated=self.root/'unrelated'
        unrelated.write_text('keep me')
        (self.run/'STOP').symlink_to(unrelated)
        with self.assertRaises(ValueError):
            self.invoke('stop','--output',str(self.run))
        self.assertEqual(unrelated.read_text(),'keep me')

    def test_watch_does_not_read_symlink_metadata(self):
        unrelated=self.root/'unrelated'
        unrelated.write_text('{"secret":"not for output"}')
        (self.run/'status.json').symlink_to(unrelated)
        with self.assertRaises(ValueError):
            self.invoke('watch','--output',str(self.run),'--once')


if __name__ == '__main__':
    unittest.main()
