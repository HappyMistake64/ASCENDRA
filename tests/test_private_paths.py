import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ascendra.agent import EvolutionAgent
from ascendra.provider import CodexCLIProvider


class PrivatePathTest(unittest.TestCase):
    def test_nested_private_files_and_symlink_alias_are_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private = root / '.ascendra_hidden' / 'nested' / 'test.py'
            private.parent.mkdir(parents=True)
            private.write_text('private sentinel')
            (root / 'alias.py').symlink_to(private)
            (root / 'task.py').write_text('public sentinel')
            self.assertEqual(EvolutionAgent(None)._files(root),
                             {'task.py': 'public sentinel'})

    def test_private_edits_are_rejected_even_without_explicit_globs(self):
        class Provider:
            def propose_edits(self, **kwargs):
                return {self.path: 'replacement'}

        for rel in ('.ascendra_hidden/nested/test.py',
                    'sub/.ascendra_hidden/test.py', '.ascendra_hidden'):
            with self.subTest(path=rel), tempfile.TemporaryDirectory() as td:
                provider = Provider()
                provider.path = rel
                with self.assertRaisesRegex(ValueError, 'hidden evaluator path'):
                    EvolutionAgent(provider).solve('strategy', 'task', '', Path(td))
                self.assertEqual(list(Path(td).iterdir()), [])

    def test_custom_private_directory_is_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private = root / 'private' / 'nested' / 'test.py'
            private.parent.mkdir(parents=True)
            private.write_text('private sentinel')
            self.assertEqual(EvolutionAgent(None)._files(root, ['private/**']), {})

    def test_codex_starts_in_separate_directory(self):
        def run(command, **kwargs):
            cwd = Path(kwargs['cwd'])
            self.assertNotEqual(cwd, Path.cwd())
            self.assertEqual({p.name for p in cwd.iterdir()}, {'schema.json'})
            Path(command[command.index('-o') + 1]).write_text(json.dumps({'ready': True}))
            return subprocess.CompletedProcess(command, 0, '', '')

        with patch('ascendra.provider.shutil.which', return_value='/fake/codex'), \
                patch('ascendra.provider.subprocess.run', side_effect=run):
            provider = CodexCLIProvider(model='gpt-6-astra', effort='low')
            self.assertEqual(provider._exec('neutral preflight', {}), {'ready': True})
