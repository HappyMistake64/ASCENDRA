import time
from .models import TaskResult,EvalSummary
from .subscription import ProviderBlocked
class Evaluator:
    def __init__(self,sandbox,agent,store):self.sandbox=sandbox;self.agent=agent;self.store=store
    def evaluate(self,strategy,tasks):
        started=time.time();results=[];total_duration=0.0
        for task in tasks:
            ws=self.sandbox.create(task);changed=[];err=None
            before_usage=self.agent.provider.usage_snapshot() if hasattr(self.agent.provider,'usage_snapshot') else {'model_calls':0,'input_tokens':0,'output_tokens':0}
            try:
                changed=self.agent.solve(strategy.system_prompt,task.id,task.description,ws,task.hidden_globs)
                rc,out,stderr,dur=self.sandbox.run(ws,task.test_command,task.timeout_s);solved=rc==0;total_duration+=dur
            except ProviderBlocked:
                # Provider failures invalidate a run; never score them as task failures.
                raise
            except Exception as e:
                rc=125;out='';stderr='';dur=0.0;solved=False;err=f'{type(e).__name__}: {e}'
            finally:self.sandbox.cleanup(ws)
            after_usage=self.agent.provider.usage_snapshot() if hasattr(self.agent.provider,'usage_snapshot') else before_usage
            r=TaskResult(task.id,strategy.id,solved,rc,dur,out,stderr,changed,err,after_usage.get('model_calls',0)-before_usage.get('model_calls',0),after_usage.get('input_tokens',0)-before_usage.get('input_tokens',0),after_usage.get('output_tokens',0)-before_usage.get('output_tokens',0),0.0);results.append(r)
            self.store.event('task_result',{'task':task.id,'strategy':strategy.id,'solved':solved,'changed':changed,'error':err,'model_calls':r.model_calls,'input_tokens':r.input_tokens,'output_tokens':r.output_tokens})
        vis=[r for r,t in zip(results,tasks) if t.split=='visible'];hold=[r for r,t in zip(results,tasks) if t.split=='holdout'];solved=sum(r.solved for r in results)
        s=EvalSummary(strategy.id,len(results),solved,solved/len(results) if results else 0,len(vis),sum(r.solved for r in vis),len(hold),sum(r.solved for r in hold),total_duration,results)
        self.store.save_summary(s,started);return s
