import tempfile,unittest
from pathlib import Path
from ascendra.models import Strategy
from ascendra.cli import build
from ascendra.provider import DemoProvider
from ascendra.promotion import PromotionGate
from ascendra.evolution import EvolutionEngine
class CoreTest(unittest.TestCase):
    def test_demo_recurses_two_generations(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            # keep benchmark at project root, evidence/work in a temporary mirrored root
            temp=Path(td);(temp/'benchmarks').symlink_to(root/'benchmarks',target_is_directory=True)
            provider=DemoProvider(0);store,tasks,ev=build(temp,provider);engine=EvolutionEngine(ev,PromotionGate(),provider,store,tasks)
            champ,summary,hist=engine.run(Strategy('g0',0,None,'baseline'),2)
            self.assertEqual(champ.generation,2);self.assertEqual(summary.solved,3);self.assertTrue(all(x['decision'].promote for x in hist))
if __name__=='__main__':unittest.main()
