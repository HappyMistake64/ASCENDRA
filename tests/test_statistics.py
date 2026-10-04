import unittest
from ascendra.statistics import wilson_interval
from ascendra.models import EvalSummary,TaskResult
from ascendra.promotion import PromotionGate

def summary(sid,outcomes):
    rs=[TaskResult(k,sid,v,0 if v else 1,0) for k,v in outcomes];solved=sum(v for _,v in outcomes)
    return EvalSummary(sid,len(rs),solved,solved/len(rs),0,0,len(rs),solved,0,rs)

class StatisticsTest(unittest.TestCase):
    def test_wilson_bounds(self):
        lo,hi=wilson_interval(10,10);self.assertGreater(lo,.5);self.assertLessEqual(hi,1)
    def test_repeated_improvement_promotes(self):
        champions=[summary('c',[('a',False),('b',False),('c',True),('d',True)]) for _ in range(3)]
        candidates=[summary('n',[('a',True),('b',True),('c',True),('d',True)]) for _ in range(3)]
        d=PromotionGate().decide_repeated(champions,candidates)
        self.assertTrue(d.promote);self.assertEqual(d.verdict,'IMPROVED');self.assertEqual(d.losses,0)
    def test_repeated_regression_rejects(self):
        champions=[summary('c',[('a',True),('b',False)]) for _ in range(3)]
        candidates=[summary('n',[('a',False),('b',True)]) for _ in range(3)]
        d=PromotionGate().decide_repeated(champions,candidates)
        self.assertFalse(d.promote);self.assertEqual(d.verdict,'REGRESSED')
