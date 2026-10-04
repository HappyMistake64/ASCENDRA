"""Exercise all historical graders from actual project-local virtualenvs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import venv


class VirtualenvSandboxTests(unittest.TestCase):
    def test_copied_and_symlinked_interpreters_keep_host_files_private(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ascendra-venv-', dir=repository) as temporary:
            directory = Path(temporary)
            sentinel = directory/'host-private.txt'
            sentinel.write_text('Private host data must not enter candidate mounts.')
            candidate = (
                'from pathlib import Path\n'
                f'assert not Path({str(sentinel)!r}).exists()\n'
                'print(int(input()) * 2)\n'
            )
            driver = '''import json, sys
from pathlib import Path
from ascendra import method_research, method_research_v2, method_research_v3
candidate = sys.argv[1]
base = str(Path(sys._base_executable).resolve())
assert sys.executable != base
results = {}
for module in (method_research, method_research_v2, method_research_v3):
    command = module.sandbox_command(Path('/unused-task'))
    assert command[command.index('--') + 1] == base
    results[module.__name__] = module.evaluate(
        candidate, [{'input': '21\\n', 'output': '42\\n'}], public=True)
print(json.dumps(results))
'''
            for symlinks in (False, True):
                with self.subTest(symlinks=symlinks):
                    environment = directory/('symlinked' if symlinks else 'copied')
                    venv.EnvBuilder(with_pip=False, symlinks=symlinks).create(environment)
                    result = subprocess.run(
                        [str(environment/'bin/python'), '-c', driver, candidate],
                        cwd=repository, text=True, capture_output=True, timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    results = json.loads(result.stdout)
                    self.assertEqual(len(results), 3)
                    for module, evidence in results.items():
                        self.assertTrue(evidence['solved'], (module, evidence))
                    self.assertTrue(sentinel.exists())


if __name__ == '__main__':
    unittest.main()
