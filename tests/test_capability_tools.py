import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from ascendra.capability_tools import ToolCatalog


class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        self.root.mkdir()
        (self.root / 'tests').mkdir()
        (self.root / 'module.py').write_text('VALUE = 7\n')
        (self.root / 'tests' / 'test_module.py').write_text(
            'import unittest\nimport module\nclass TestValue(unittest.TestCase):\n'
            ' def test_value(self): self.assertEqual(module.VALUE, 7)\n')
        self.catalog = ToolCatalog(self.root, writable_paths=['module.py', 'new.py'])

    def test_descriptors_and_unknown_tool_are_machine_readable(self):
        descriptors = self.catalog.descriptors()
        self.assertEqual({d['name'] for d in descriptors},
                         {'list_files', 'read_file', 'search_text', 'run_tests', 'write_file'})
        descriptors[0]['input_schema']['properties'].clear()
        self.assertIn('path', self.catalog.descriptors()[0]['input_schema']['properties'])
        result = self.catalog.execute('shell', {'command': 'whoami'})
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['data'])
        json.dumps(result)

    def test_read_search_list_and_private_exclusion(self):
        for name in ('.ascendra_hidden', '.ascendra', '.git', 'auth'):
            (self.root / name).mkdir()
            (self.root / name / 'private.txt').write_text('SECRET')
        (self.root / '.env').write_text('SECRET')
        for tool, args in [('list_files', {}), ('search_text', {'query': 'SECRET'})]:
            result = self.catalog.execute(tool, args)
            self.assertEqual(result['status'], 'ok', result)
            self.assertNotIn('private.txt', json.dumps(result))
            self.assertNotIn('.env', json.dumps(result))
        read = self.catalog.execute('read_file', {'path': 'module.py'})
        self.assertEqual(read['data']['content'], 'VALUE = 7\n')
        search = self.catalog.execute('search_text', {'query': 'VALUE'})
        self.assertEqual(search['status'], 'ok')
        self.assertTrue(any(m['path'] == 'module.py' for m in search['data']['matches']))

    def test_traversal_private_and_symlink_escapes_are_blocked(self):
        external = Path(self.temporary.name) / 'secret.txt'
        external.write_text('HOST SECRET')
        (self.root / 'link.txt').symlink_to(external)
        (self.root / 'linked_dir').symlink_to(self.root / 'tests', target_is_directory=True)
        for path in ('../secret.txt', str(external), '.env', '.git/config', 'auth/token',
                     '.ascendra_hidden/cases.json', 'link.txt', 'linked_dir/test_module.py',
                     'tests/../module.py', 'tests\\test_module.py'):
            with self.subTest(path=path):
                result = self.catalog.execute('read_file', {'path': path})
                self.assertEqual(result['status'], 'error')
                self.assertNotIn('HOST SECRET', json.dumps(result))
        self.assertNotIn('link.txt', self.catalog.execute('list_files', {})['data']['files'])
        with self.assertRaises(ValueError): ToolCatalog(self.root, writable_paths=['../secret.txt'])

    def test_standard_credential_paths_are_excluded_from_tools_and_snapshots(self):
        private_paths = ['.codex/config.toml', '.docker/config.json', '.kube/config',
                         '.netrc', '.npmrc', '.pypirc', 'nested/.codex/config.toml']
        for relative in private_paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('PRIVATE CREDENTIAL SENTINEL')
        files = self.catalog.execute('list_files', {})['data']['files']
        matches = self.catalog.execute('search_text', {'query': 'PRIVATE CREDENTIAL SENTINEL'})
        self.assertEqual(matches['data']['matches'], [])
        snapshot = Path(self.temporary.name) / 'snapshot'
        snapshot.mkdir()
        self.catalog._snapshot(snapshot)
        for relative in private_paths:
            with self.subTest(path=relative):
                self.assertNotIn(relative, files)
                self.assertEqual(self.catalog.execute('read_file', {'path': relative})['status'], 'error')
                self.assertFalse((snapshot / relative).exists())
                with self.assertRaises(ValueError):
                    ToolCatalog(self.root, writable_paths=[relative])
        self.assertEqual((snapshot / 'module.py').read_text(), 'VALUE = 7\n')

    def test_hard_links_are_not_accessible(self):
        external = Path(self.temporary.name) / 'shared.txt'
        external.write_text('HOST SECRET')
        os.link(external, self.root / 'shared.txt')
        self.assertEqual(self.catalog.execute('read_file', {'path': 'shared.txt'})['status'], 'error')
        self.assertNotIn('shared.txt', self.catalog.execute('list_files', {})['data']['files'])

    def test_write_requires_allowlist_and_matching_hash_and_is_atomic(self):
        original = (self.root / 'module.py').read_bytes()
        bad = self.catalog.execute('write_file', {'path': 'module.py', 'content': 'bad',
                                                  'expected_sha256': '0' * 64})
        self.assertEqual(bad['status'], 'error')
        self.assertEqual((self.root / 'module.py').read_bytes(), original)
        denied = self.catalog.execute('write_file', {'path': 'tests/test_module.py', 'content': 'bad'})
        self.assertEqual(denied['status'], 'error')
        result = self.catalog.execute('write_file', {'path': 'module.py', 'content': 'VALUE = 8\n',
                        'expected_sha256': hashlib.sha256(original).hexdigest()})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual((self.root / 'module.py').read_text(), 'VALUE = 8\n')
        self.assertFalse(list(self.root.glob('.capability-write-*')))
        self.assertEqual(self.catalog.execute('write_file', {'path': 'new.py', 'content': 'new'})['status'], 'ok')

    def test_write_rejects_target_and_parent_symlinks(self):
        (self.root / 'new.py').symlink_to(self.root / 'module.py')
        result = self.catalog.execute('write_file', {'path': 'new.py', 'content': 'bad'})
        self.assertEqual(result['status'], 'error')
        (self.root / 'linked').symlink_to(self.root / 'tests', target_is_directory=True)
        catalog = ToolCatalog(self.root, writable_paths=['linked/test_module.py'])
        result = catalog.execute('write_file', {'path': 'linked/test_module.py', 'content': 'bad'})
        self.assertEqual(result['status'], 'error')
        self.assertEqual((self.root / 'module.py').read_text(), 'VALUE = 7\n')

    def test_real_sandbox_pass_and_failure_are_valid_tool_results(self):
        result = self.catalog.execute('run_tests', {})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['tests_run'], 1)
        self.assertTrue(result['data']['successful'])
        (self.root / 'module.py').write_text('VALUE = 0\n')
        result = self.catalog.execute('run_tests', {})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['failures'], 1)
        self.assertFalse(result['data']['successful'])
        self.assertIn('FAIL', result['data']['output'])

    def test_real_sandbox_test_error_and_empty_suite(self):
        (self.root / 'tests' / 'test_module.py').write_text(
            'import unittest\nclass TestFailure(unittest.TestCase):\n'
            ' def test_error(self): raise RuntimeError("intentional")\n')
        result = self.catalog.execute('run_tests', {})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['errors'], 1)
        result = self.catalog.execute('run_tests', {'pattern': 'not_present*.py'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['tests_run'], 0)
        self.assertFalse(result['data']['successful'])

    def test_real_sandbox_is_readonly_private_filtered_host_hidden_and_network_off(self):
        secret = Path(self.temporary.name) / 'outside-secret.txt'
        secret.write_text('HOST SECRET')
        (self.root / '.env').write_text('SECRET')
        (self.root / '.ascendra_hidden').mkdir()
        (self.root / '.ascendra_hidden' / 'cases.json').write_text('SECRET')
        (self.root / 'outside-link').symlink_to(secret)
        (self.root / 'tests' / 'test_module.py').write_text(
            'import unittest, pathlib, socket, os\nclass TestIsolation(unittest.TestCase):\n'
            ' def test_isolation(self):\n'
            f'  self.assertFalse(pathlib.Path({str(secret)!r}).exists())\n'
            '  self.assertFalse(pathlib.Path("/project/.env").exists())\n'
            '  self.assertFalse(pathlib.Path("/project/.ascendra_hidden").exists())\n'
            '  self.assertFalse(pathlib.Path("/project/outside-link").exists())\n'
            '  with self.assertRaises(OSError): pathlib.Path("/project/module.py").write_text("changed")\n'
            '  with self.assertRaises(OSError):\n'
            '   s=socket.socket(); s.settimeout(0.2)\n'
            '   try: s.connect(("1.1.1.1", 443))\n'
            '   finally: s.close()\n'
            '  self.assertNotIn("CAPABILITY_TEST_SECRET", os.environ)\n')
        previous = os.environ.get('CAPABILITY_TEST_SECRET')
        os.environ['CAPABILITY_TEST_SECRET'] = 'SECRET'
        try:
            result = self.catalog.execute('run_tests', {})
        finally:
            if previous is None: os.environ.pop('CAPABILITY_TEST_SECRET', None)
            else: os.environ['CAPABILITY_TEST_SECRET'] = previous
        self.assertEqual(result['status'], 'ok', result)
        self.assertTrue(result['data']['successful'], result)
        self.assertEqual((self.root / 'module.py').read_text(), 'VALUE = 7\n')

    def test_tool_argument_schema_rejects_shell_injection_surface(self):
        for args in ({'command': 'touch /tmp/evil'}, {'start_dir': '../outside'},
                     {'pattern': '../test*.py'}, {'start_dir': 4}):
            self.assertEqual(self.catalog.execute('run_tests', args)['status'], 'error')

    def test_untrusted_output_is_bounded(self):
        (self.root / 'tests' / 'test_module.py').write_text(
            'import unittest\nclass TestOutput(unittest.TestCase):\n'
            ' def test_output(self): print("x"*200000)\n')
        result = self.catalog.execute('run_tests', {})
        self.assertEqual(result['status'], 'ok', result)
        self.assertTrue(result['data']['output_truncated'])
        self.assertLessEqual(len(result['data']['output']), 32768)


if __name__ == '__main__':
    unittest.main()
