import uuid
from .models import Strategy

class EvolutionEngine:
    def __init__(self,evaluator,gate,provider,store,tasks):self.evaluator=evaluator;self.gate=gate;self.provider=provider;self.store=store;self.tasks=tasks
    def _tasks_for_generation(self,generation):
        grouped=sorted({t.eval_group for t in self.tasks if t.split=='holdout' and t.eval_group>0})
        if not grouped:return self.tasks
        group=grouped[(generation-1)%len(grouped)]
        return [t for t in self.tasks if t.split=='visible' or (t.split=='holdout' and t.eval_group==group)]
    @staticmethod
    def _failure_summary(summary):
        failures=[]
        for r in summary.results:
            # Raw tracebacks/output can contain hidden test source or candidate exfiltration.
            if not r.solved:failures.append({'task':r.task_id,'error':'timeout' if r.returncode == 124 else 'evaluation failed'})
        if not failures:return 'No failures in the current evaluation. Improve generality, robustness, and minimality without regressing solved tasks.'
        return 'Observed failures:\n'+'\n'.join(f"- {x['task']}: {x['error']}" for x in failures)
    def mutate(self,parent,generation,parent_summary):
        prompt=self.provider.mutate_prompt(parent_prompt=parent.system_prompt,failure_summary=self._failure_summary(parent_summary),generation=generation)
        s=Strategy(f'g{generation}-{uuid.uuid4().hex[:8]}',generation,parent.id,prompt,{**parent.metadata,'kind':'candidate','mutation_source':'verified_evaluator_evidence'})
        self.store.save_strategy(s);return s
    def _evaluate_n(self,strategy,tasks,replicates):return [self.evaluator.evaluate(strategy,tasks) for _ in range(replicates)]
    def run(self,initial,max_generations=3,on_generation=None,replicates=1):
        if replicates<1:raise ValueError('replicates must be >= 1')
        champion=initial;self.store.save_strategy(champion)
        baseline=self.evaluator.evaluate(champion,self._tasks_for_generation(1));self.store.promote(champion.generation,champion.id)
        history=[];last_summary=baseline
        for gen in range(champion.generation+1,champion.generation+1+max_generations):
            tasks=self._tasks_for_generation(gen);champ_summaries=self._evaluate_n(champion,tasks,replicates)
            cand=self.mutate(champion,gen,champ_summaries[0]);cand_summaries=self._evaluate_n(cand,tasks,replicates)
            decision=self.gate.decide(champ_summaries[0],cand_summaries[0]) if replicates==1 else self.gate.decide_repeated(champ_summaries,cand_summaries)
            item={'generation':gen,'eval_group':sorted({t.eval_group for t in tasks if t.split=='holdout'}),'champion':champion.id,'candidate':cand.id,'decision':decision,'champion_summary':champ_summaries[-1],'candidate_summary':cand_summaries[-1],'replicates':replicates};history.append(item)
            self.store.event('selection',{'generation':gen,'eval_group':item['eval_group'],'candidate':cand.id,'promote':decision.promote,'verdict':decision.verdict,'reason':decision.reason,'delta':decision.holdout_delta,'regressions':decision.regressions,'gains':decision.gains,'losses':decision.losses,'ties':decision.ties,'confidence_low':decision.confidence_low,'confidence_high':decision.confidence_high,'replicates':replicates})
            if decision.promote:
                champion=cand;last_summary=cand_summaries[-1];self.store.promote(gen,champion.id);self.store.event('checkpoint',{'generation':gen,'strategy_id':champion.id,'status':'accepted'})
            else:
                last_summary=champ_summaries[-1];self.store.event('rollback',{'generation':gen,'candidate':cand.id,'restored_champion':champion.id,'reason':decision.reason})
            if on_generation:on_generation(item)
            if not decision.promote:
                # G2 is only a recursive successor when G1 was accepted.
                break
        return champion,last_summary,history
