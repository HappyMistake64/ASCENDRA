import tempfile, unittest
from pathlib import Path
from ascendra.benchmark import BenchmarkRegistry
from ascendra.evolution import EvolutionEngine

class RotationTest(unittest.TestCase):
    def test_holdout_rotates(self):
        root=Path(__file__).resolve().parents[1]
        tasks=BenchmarkRegistry(root/'benchmarks'/'real_v1').load()
        e=EvolutionEngine(None,None,None,None,tasks)
        g1=e._tasks_for_generation(1); g2=e._tasks_for_generation(2)
        h1={t.id for t in g1 if t.split=='holdout'}
        h2={t.id for t in g2 if t.split=='holdout'}
        self.assertTrue(h1); self.assertTrue(h2); self.assertTrue(h1.isdisjoint(h2))
        self.assertEqual({t.id for t in g1 if t.split=='visible'}, {t.id for t in g2 if t.split=='visible'})
