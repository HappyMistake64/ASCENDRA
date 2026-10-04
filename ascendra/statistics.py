from __future__ import annotations
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class PairedStats:
    gains:int; losses:int; ties:int; discordant:int; win_rate:float; ci_low:float; ci_high:float

def wilson_interval(successes:int,total:int,z:float=1.96)->tuple[float,float]:
    if total<=0:return 0.0,1.0
    p=successes/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    margin=z*math.sqrt((p*(1-p)/total)+(z*z/(4*total*total)))/den
    return max(0.0,center-margin),min(1.0,center+margin)

def paired_stats(champion_summaries,candidate_summaries,holdout_only=True):
    gains=losses=ties=0
    for champion,candidate in zip(champion_summaries,candidate_summaries):
        c={r.task_id:r for r in champion.results};n={r.task_id:r for r in candidate.results}
        allowed={r.task_id for r in champion.results[-champion.holdout_total:]} if holdout_only and champion.holdout_total else set(c)
        for task_id in sorted(set(c)&set(n)):
            if task_id not in allowed:continue
            a,b=c[task_id].solved,n[task_id].solved
            if not a and b:gains+=1
            elif a and not b:losses+=1
            else:ties+=1
    discordant=gains+losses;rate=gains/discordant if discordant else .5
    low,high=wilson_interval(gains,discordant)
    return PairedStats(gains,losses,ties,discordant,rate,low,high)
