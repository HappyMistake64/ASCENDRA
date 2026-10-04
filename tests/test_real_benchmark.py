import tempfile,unittest
from pathlib import Path
from ascendra.benchmark import BenchmarkRegistry
from ascendra.sandbox import Sandbox

class RealBenchmarkTest(unittest.TestCase):
    def test_every_real_task_has_private_test_and_baseline_fails(self):
        root=Path(__file__).resolve().parents[1];tasks=BenchmarkRegistry(root/'benchmarks'/'real_v1').load()
        self.assertEqual(len(tasks),10)
        with tempfile.TemporaryDirectory() as td:
            sb=Sandbox(Path(td));failed=0
            for task in tasks:
                self.assertTrue((task.source_dir/'.ascendra_hidden/test.py').exists())
                ws=sb.create(task);rc,*_=sb.run(ws,task.test_command,task.timeout_s);failed+=rc!=0;sb.cleanup(ws)
            self.assertGreaterEqual(failed,8)
