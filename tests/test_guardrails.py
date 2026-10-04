import tempfile,unittest
from pathlib import Path
from ascendra.sandbox import Sandbox,SandboxViolation
from ascendra.models import EvalSummary,TaskResult
from ascendra.promotion import PromotionGate
class GuardrailTest(unittest.TestCase):
    def test_command_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            s=Sandbox(Path(td))
            with self.assertRaises(SandboxViolation):s.run(Path(td),['bash','-lc','echo no'],1)
    def test_regression_blocks_promotion(self):
        a=TaskResult('x','a',True,0,0);b=TaskResult('x','b',False,1,0)
        old=EvalSummary('a',1,1,1,0,0,1,1,0,[a]);new=EvalSummary('b',1,0,0,0,0,1,0,0,[b])
        self.assertFalse(PromotionGate().decide(old,new).promote)
if __name__=='__main__':unittest.main()

class HiddenEvaluatorTest(unittest.TestCase):
    def test_hidden_files_are_not_exposed_to_agent_snapshot(self):
        from ascendra.agent import EvolutionAgent
        class P: pass
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.ascendra_hidden').mkdir()
            (root/'task.py').write_text('x=1')
            (root/'.ascendra_hidden'/'test.py').write_text('SECRET=42')
            files=EvolutionAgent(P())._files(root,['.ascendra_hidden/**'])
            self.assertIn('task.py',files)
            self.assertNotIn('.ascendra_hidden/test.py',files)
