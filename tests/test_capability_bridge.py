from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ascendra import capability_bridge as bridge
from ascendra.capability_memory import ExperienceStore


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'autonomous-test'
        self.root.mkdir()
        self.write('configuration.json', dict(mode='autonomous', max_agents=4,
            max_calls=60, max_steps=8, minutes=30, mission='Inspect'))
        self.write('status.json', dict(state='working', round=1,
            mission='Inspect /workspace/private/project; token=hidden and Bearer abcdef',
            pid=123, output='/workspace/private/project', usage={'calls':3}, agents=[dict(
                id='r1-w1', state='running', task={'title':'Inspect', 'goal':'Learn'},
                output='/private/worker', progress={'step':2, 'state':'deciding', 'raw_prompt':'secret'})]))

    def write(self, relative, data):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_snapshot_exports_only_declared_sanitized_fields_without_initializing_memory(self):
        self.write('round-001/plan.json', dict(rationale='Find evidence', tasks=[dict(title='Inspect',goal='Read')]))
        self.write('round-001/worker-01/result.json', dict(raw_prompt='secret prompt', changes=[dict(
            path='ascendra/thing.py', patch='private source', before_sha256='a'*64, after_sha256='b'*64)]))
        (self.root/'events.jsonl').write_text(
            json.dumps(dict(event='worker_started', at=1, output='/host/path', message='sensitive-token'))+'\n'+
            '{"event":"partial"')
        result = bridge.snapshot(self.root, token='sensitive-token')
        encoded = json.dumps(result)
        for forbidden in ('/workspace/', '/host/', '/private/', 'raw_prompt', 'private source',
                          'sensitive-token', 'hidden', 'abcdef'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result['run_id'], self.root.name)
        self.assertEqual(result['changes'][0]['path'], 'ascendra/thing.py')
        self.assertEqual(result['changes'][0]['after_sha256'], 'b'*64)
        self.assertEqual(len(result['rounds']), 1)
        self.assertEqual(len(result['events']), 1)
        self.assertFalse((self.root/'memory').exists())
        self.assertNotIn('output', result['agents'][0])

    def test_existing_capability_journal_is_validated_without_writes(self):
        store=ExperienceStore(self.root/'memory')
        identifier=store.propose(dict(name='Inspect', description='Read source', motivation='Evidence',
            steps=[dict(tool='read_file', arguments={'path':'x.py'})], success_criteria='File read'))
        before={path.name:(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.root/'memory').iterdir()}
        self.assertEqual(bridge.snapshot(self.root)['capabilities'][0]['id'], identifier)
        after={path.name:(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.root/'memory').iterdir()}
        self.assertEqual(before, after)
        journal=json.loads((self.root/'memory'/'experience.json').read_text())
        journal['sha256']='0'*64
        self.write('memory/experience.json', journal)
        with self.assertRaises(ValueError): bridge.snapshot(self.root)

    def test_fifty_agents_and_tasks_preserve_each_allocated_call_limit(self):
        tasks = [dict(title='Worker '+str(index), goal='Inspect') for index in range(50)]
        self.write('status.json', dict(state='working', agents=[dict(id='r1-w'+str(index),
            state='running', task=task, call_limit=index+1, progress={'step':1})
            for index, task in enumerate(tasks)]))
        self.write('round-001/plan.json', dict(rationale='Parallel inspection', tasks=tasks))
        (self.root/'events.jsonl').write_text(json.dumps(dict(event='plan_selected', tasks=tasks))+'\n')
        payload=bridge.snapshot(self.root)
        self.assertEqual(len(payload['agents']),50)
        self.assertEqual([agent['call_limit'] for agent in payload['agents']],list(range(1,51)))
        self.assertEqual(len(payload['rounds'][0]['tasks']),50)
        self.assertEqual(len(payload['events'][0]['tasks']),50)

    def test_symlink_and_oversized_metadata_are_rejected(self):
        outside=Path(self.temporary.name)/'outside'
        outside.write_text('{"state":"secret"}')
        (self.root/'status.json').unlink()
        (self.root/'status.json').symlink_to(outside)
        with self.assertRaises(ValueError): bridge.snapshot(self.root)
        (self.root/'status.json').unlink()
        (self.root/'status.json').write_text('x'*(bridge.MAX_BYTES+1))
        with self.assertRaises(ValueError): bridge.snapshot(self.root)

    def test_payload_is_bounded_and_events_keep_latest_fifty(self):
        with (self.root/'events.jsonl').open('w') as stream:
            for index in range(100):
                stream.write(json.dumps(dict(event='event', at=index, message='ž'*4000), ensure_ascii=False)+'\n')
        payload=bridge.snapshot(self.root)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), bridge.MAX_BYTES)
        self.assertEqual(len(payload['events']), 50)
        self.assertEqual(payload['events'][-1]['at'], 99)

    def test_https_authentication_and_redirect_rejection(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{"run_id":"test","stop_requested":false}'
        opener=Mock()
        opener.open.return_value=response
        with patch.object(bridge.urllib.request,'build_opener',return_value=opener):
            bridge.post('https://example.test', 'credential', {'run_id':'test'})
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://example.test/api/ingest')
        self.assertEqual(request.get_header('Oai-sites-authorization'),'Bearer credential')
        self.assertEqual(opener.open.call_args.kwargs['timeout'],10)
        with self.assertRaises(ValueError):
            bridge._NoRedirect().redirect_request(None,None,302,'',{},'https://other.test')
        for origin in ('http://example.test','https://user:secret@example.test','https://example.test/path',
                       'https://example.test?token=secret','https://example.test#fragment'):
            with self.subTest(origin=origin), self.assertRaises(ValueError): bridge.endpoint(origin)

    def test_remote_stop_requires_matching_run_and_never_executes_other_commands(self):
        with patch.object(bridge,'post',return_value={'run_id':'other','stop_requested':True}):
            self.assertEqual(bridge.bridge(self.root,'https://example.test','credential',once=True),1)
        self.assertFalse((self.root/'STOP').exists())
        with patch.object(bridge,'post',return_value={
                'run_id':self.root.name,'stop_requested':True,'command':'delete files'}):
            self.assertEqual(bridge.bridge(self.root,'https://example.test','credential',once=True),0)
        self.assertTrue((self.root/'STOP').is_file())
        self.assertTrue((self.root/'status.json').exists())

    def test_stop_refuses_symlinks_and_pipes_and_is_idempotent(self):
        outside=Path(self.temporary.name)/'outside'
        outside.write_text('preserve')
        (self.root/'STOP').symlink_to(outside)
        with self.assertRaises(ValueError): bridge.request_stop(self.root)
        self.assertEqual(outside.read_text(),'preserve')
        (self.root/'STOP').unlink()
        os.mkfifo(self.root/'STOP')
        with self.assertRaises(ValueError): bridge.request_stop(self.root)
        (self.root/'STOP').unlink()
        bridge.request_stop(self.root)
        bridge.request_stop(self.root)

    def test_errors_never_persist_credential_and_terminal_snapshot_exits(self):
        with patch.object(bridge,'post',side_effect=RuntimeError('credential /private/path')):
            self.assertEqual(bridge.bridge(self.root,'https://example.test','credential',once=True),1)
        health=(self.root/'bridge_status.json').read_text()
        self.assertNotIn('credential',health)
        self.assertNotIn('/private',health)
        self.assertEqual(json.loads(health)['error'],'RuntimeError')
        self.write('status.json',{'state':'deadline'})
        with patch.object(bridge,'post',return_value={'run_id':self.root.name,'stop_requested':False}), \
                patch.object(bridge.time,'sleep') as sleep:
            self.assertEqual(bridge.bridge(self.root,'https://example.test','credential'),0)
        sleep.assert_not_called()

    def test_stdin_token_never_printed_and_unmarked_run_rejected(self):
        with patch.object(bridge.sys,'stdin',io.StringIO('{"token":"secret-stdin"}\n')), \
                patch.object(bridge,'bridge',return_value=0) as run:
            self.assertEqual(bridge.main(['--output',str(self.root),'--site-origin','https://example.test','--token-stdin']),0)
        self.assertEqual(run.call_args.args[2],'secret-stdin')
        (self.root/'configuration.json').unlink()
        with self.assertRaises(ValueError): bridge.authorized_run(self.root)
        captured=io.StringIO()
        with redirect_stderr(captured):
            self.assertEqual(bridge.main(['--output',str(self.root),'--site-origin','https://example.test']),1)
        self.assertNotIn('secret-stdin',captured.getvalue())


if __name__ == '__main__':
    unittest.main()
