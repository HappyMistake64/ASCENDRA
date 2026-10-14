from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from ascendra.local_llm import LocalDecider
from ascendra.v4_ledger import BudgetExceeded, ProviderFailure
from ascendra.studio_cli import parser


SCHEMA = {'type': 'object', 'properties': {'ready': {'type': 'boolean'}},
          'required': ['ready'], 'additionalProperties': False}


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.requests = []
        self.response = {'model': 'test-local', 'done': True, 'done_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '{"ready":true}'},
                         'prompt_eval_count': 14, 'eval_count': 5}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def decider(self, **kwargs):
        return LocalDecider(Path(self.temp.name) / 'provider', endpoint=self.url,
                            model='test-local', **kwargs)

    def test_real_http_shape_schema_accounting_and_no_native_tools(self):
        decide = self.decider(max_calls=1)
        self.assertEqual(decide({'instruction': 'check'}, SCHEMA), {'ready': True})
        self.assertFalse(self.requests[0]['stream'])
        self.assertNotIn('tools', self.requests[0])
        self.assertEqual(self.requests[0]['format'], SCHEMA)
        self.assertEqual(decide.ledger.summary()['known_tokens'], 19)
        with self.assertRaises(BudgetExceeded):
            decide({}, SCHEMA)
        self.assertEqual(len(self.requests), 1)

    def test_failed_call_is_charged_and_never_retried(self):
        self.response['done_reason'] = 'length'
        decide = self.decider(max_calls=1)
        with self.assertRaises(ProviderFailure):
            decide({}, SCHEMA)
        self.assertEqual(decide.ledger.summary()['calls'], 1)
        with self.assertRaises(BudgetExceeded):
            decide({}, SCHEMA)
        self.assertEqual(len(self.requests), 1)

    def test_schema_mismatch_native_tools_and_missing_usage_rejected(self):
        for index, mutation in enumerate([
            {'message': {'role': 'assistant', 'content': '{"ready":"yes"}'}},
            {'message': {'role': 'assistant', 'content': '{"ready":true}', 'tool_calls': [{}]}},
            {'prompt_eval_count': None},
        ]):
            with self.subTest(index=index):
                original = dict(self.response)
                self.response.update(mutation)
                decide = LocalDecider(Path(self.temp.name) / str(index), endpoint=self.url, model='test-local')
                with self.assertRaises(ProviderFailure):
                    decide({}, SCHEMA)
                self.response = original

    def test_large_input_rejected_before_call(self):
        decide = self.decider()
        with self.assertRaises(ValueError):
            decide({'text': 'x' * 20000}, SCHEMA)
        self.assertEqual(self.requests, [])
        self.assertEqual(decide.ledger.summary()['calls'], 0)

    def test_no_remote_redirect_or_cloud_configuration(self):
        for endpoint in ['https://api.example.com', 'http://localhost:11434',
                         'http://127.0.0.1:11434/path', 'http://user:pass@127.0.0.1:11434']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                LocalDecider(self.temp.name, endpoint=endpoint)
        for model in ['qwen:cloud', 'https://example.com/model', 'remote/model']:
            with self.subTest(model=model), self.assertRaises(ValueError):
                LocalDecider(self.temp.name, model=model)

    def test_budget_survives_reopening(self):
        self.decider(max_calls=1)({}, SCHEMA)
        with self.assertRaises(BudgetExceeded):
            self.decider(max_calls=1)({}, SCHEMA)
        self.assertEqual(len(self.requests), 1)

    def test_studio_defaults_to_local_provider(self):
        args = parser().parse_args(['--data', self.temp.name, 'doctor'])
        self.assertEqual(args.provider, 'ollama')
        self.assertIsNone(args.model)

    def test_existing_budget_cannot_be_enlarged(self):
        self.decider(max_calls=1)
        with self.assertRaises(ValueError):
            self.decider(max_calls=2)


if __name__ == '__main__':
    unittest.main()
