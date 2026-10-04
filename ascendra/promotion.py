from dataclasses import dataclass
from .statistics import paired_stats

@dataclass(frozen=True)
class PromotionDecision:
    promote:bool;reason:str;holdout_delta:float;regressions:list[str]
    verdict:str='INCONCLUSIVE';gains:int=0;losses:int=0;ties:int=0;confidence_low:float=0.0;confidence_high:float=1.0

class PromotionGate:
    def __init__(self,min_holdout_delta=.05,confidence_threshold=.50):self.min_holdout_delta=min_holdout_delta;self.confidence_threshold=confidence_threshold
    def _delta(self,c,n):
        a=c.holdout_solved/c.holdout_total if c.holdout_total else c.solve_rate
        b=n.holdout_solved/n.holdout_total if n.holdout_total else n.solve_rate
        return b-a
    def decide(self,champion,candidate):
        cr={r.task_id:r for r in champion.results};nr={r.task_id:r for r in candidate.results}
        regressions=sorted(k for k,v in cr.items() if v.solved and k in nr and not nr[k].solved);delta=self._delta(champion,candidate)
        if regressions:return PromotionDecision(False,'regression detected',delta,regressions,'REGRESSED')
        if delta<self.min_holdout_delta:return PromotionDecision(False,f'holdout delta {delta:.3f} below {self.min_holdout_delta:.3f}',delta,[],'INCONCLUSIVE')
        return PromotionDecision(True,'verified holdout improvement',delta,[],'IMPROVED')
    def decide_repeated(self,champions,candidates):
        if not champions or len(champions)!=len(candidates):raise ValueError('paired repeated evaluation requires equal non-empty replicate sets')
        stats=paired_stats(champions,candidates,True)
        ct=sum(s.holdout_total for s in champions);nt=sum(s.holdout_total for s in candidates)
        cs=sum(s.holdout_solved for s in champions);ns=sum(s.holdout_solved for s in candidates)
        delta=(ns/nt if nt else 0)-(cs/ct if ct else 0)
        cc={};nc={}
        for c,n in zip(champions,candidates):
            for r in c.results:cc[r.task_id]=cc.get(r.task_id,0)+int(r.solved)
            for r in n.results:nc[r.task_id]=nc.get(r.task_id,0)+int(r.solved)
        regressions=sorted(k for k,v in cc.items() if nc.get(k,0)<v)
        args=(stats.gains,stats.losses,stats.ties,stats.ci_low,stats.ci_high)
        if regressions:return PromotionDecision(False,'aggregate task regression detected',delta,regressions,'REGRESSED',*args)
        if delta<self.min_holdout_delta or stats.gains==0:return PromotionDecision(False,'no sufficient repeated holdout gain',delta,[],'INCONCLUSIVE',*args)
        if stats.ci_low<=self.confidence_threshold:return PromotionDecision(False,f'paired evidence inconclusive: 95% lower bound {stats.ci_low:.3f}',delta,[],'INCONCLUSIVE',*args)
        return PromotionDecision(True,'repeated paired holdout improvement',delta,[],'IMPROVED',*args)
