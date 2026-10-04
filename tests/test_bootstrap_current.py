"""The legacy entrypoint must never overwrite the checked-in implementation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io


class BootstrapCurrentTests(unittest.TestCase):
    def load(self):
        path = Path(__file__).resolve().parents[1] / 'bootstrap_cloud.py'
        spec = importlib.util.spec_from_file_location('bootstrap_current', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_existing_sources_are_not_modified(self):
        module = self.load()
        root = Path(module.__file__).parent
        source = root / 'ascendra/capability_cli.py'
        before = source.read_bytes()
        with redirect_stdout(io.StringIO()):
            module.main()
        self.assertEqual(source.read_bytes(), before)

    def test_missing_source_fails_without_extracting_legacy_bundle(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module.__file__ = str(root / 'bootstrap_cloud.py')
            with self.assertRaisesRegex(SystemExit, 'Incomplete source checkout'):
                module.main()
            self.assertEqual(list(root.iterdir()), [])
