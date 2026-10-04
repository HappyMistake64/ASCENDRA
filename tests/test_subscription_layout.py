"""Real isolation checks for runner home and temporary-directory layouts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ascendra.subscription import ProviderBlocked, SubscriptionProvider


class SubscriptionLayoutTests(unittest.TestCase):
    def provider(self, root, codex):
        # No Codex installation or genuine authentication is used by this probe.
        provider = object.__new__(SubscriptionProvider)
        provider.root = root
        provider.codex_directory = codex
        provider.auth_file = codex/'auth.json'
        provider.bwrap = shutil.which('bwrap') or 'bwrap'
        return provider

    def test_nested_home_and_tmp_layouts_preserve_isolation(self):
        for repository_under_home in (True, False):
            with self.subTest(repository_under_home=repository_under_home), \
                    tempfile.TemporaryDirectory(prefix='ascendra-layout-', dir='/tmp') as temporary:
                parent = Path(temporary)
                home = parent/'home'
                home.mkdir()
                root = (home if repository_under_home else parent)/'work'/'repository'
                root.mkdir(parents=True)
                codex = home/'.codex'
                codex.mkdir()
                (codex/'auth.json').write_text('{"test_only":true}')
                sentinels = [root/'private-test', home/'private-home', codex/'private-state', parent/'private-tmp']
                for path in sentinels:
                    path.write_text('Artificial private sentinel')
                provider = self.provider(root, codex)
                with patch('ascendra.subscription.Path.home', return_value=home):
                    provider.verify_isolation()
                    with tempfile.TemporaryDirectory(prefix='ascendra-layout-scratch-', dir='/tmp') as temporary_scratch:
                        scratch = Path(temporary_scratch)
                        (scratch/'public-input').write_text('public')
                        script = (
                            'from pathlib import Path; import os\n'
                            f'assert list(Path({str(root)!r}).iterdir()) == []\n'
                            f'assert all(not Path(p).exists() for p in {[str(p) for p in sentinels]!r})\n'
                            f'assert Path({str(provider.auth_file)!r}).read_text() == \'{{"test_only":true}}\'\n'
                            'assert Path("public-input").read_text() == "public"\n'
                            'assert os.getppid() <= 1\n'
                            'try:\n'
                            f'    Path({str(provider.auth_file)!r}).write_text("changed")\n'
                            'except OSError:\n'
                            '    pass\n'
                            'else:\n'
                            '    raise AssertionError("Authentication bind must be read-only")\n'
                        )
                        completed = subprocess.run(
                            provider.isolated_command(['/usr/bin/python3', '-I', '-c', script], scratch),
                            capture_output=True, text=True, timeout=15,
                        )
                        self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(all(path.exists() for path in sentinels))
                self.assertEqual(provider.auth_file.read_text(), '{"test_only":true}')

    def test_repository_cannot_contain_required_visible_directories(self):
        with tempfile.TemporaryDirectory(prefix='ascendra-layout-', dir='/tmp') as temporary:
            parent = Path(temporary)
            root = parent/'repository'
            for nested in ('home', 'codex', 'scratch'):
                with self.subTest(nested=nested):
                    paths = {name: (root if name == nested else parent)/name
                             for name in ('home', 'codex', 'scratch')}
                    provider = self.provider(root, paths['codex'])
                    with patch('ascendra.subscription.Path.home', return_value=paths['home']):
                        with self.assertRaisesRegex(ProviderBlocked, 'Repository must not contain'):
                            provider.isolated_command(['true'], paths['scratch'])


if __name__ == '__main__':
    unittest.main()
