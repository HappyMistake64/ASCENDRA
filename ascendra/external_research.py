"""Preregistered transfer comparison of frozen strategies on external HumanEval tasks.

The source dataset contains evaluator-private material. This module never prints
its tests or reference solutions and never uses outcomes to select tasks.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .agent import EvolutionAgent
from .benchmark import BenchmarkRegistry
from .evaluator import Evaluator
from .models import EvalSummary, Strategy, TaskResult
from .promotion import PromotionGate
from .sandbox import Sandbox
from .store import EvidenceStore
from .subscription import ProviderBlocked, SubscriptionProvider

SOURCE_COMMIT = '6d43fb980f9fee3c892a914eda09951f772ad10d'
SOURCE_SHA256 = 'b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef'
SEED = 'ASCENDRA-external-humaneval-20-v1'
STUDY = 'external-humaneval-v1'
BENCHMARK = 'external_humaneval_v1'
STRATEGY_IDS = ('g0-baseline', 'g1-4e1dee6d')
PASS_MARKER = 'ASCENDRA_PRIVATE_CHECK_COMPLETED'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def selected_ids(ids):
    return sorted(ids, key=lambda task: sha((SEED + ':' + task).encode()))[:20]


def schedule(ids):
    # Balance order within every replicate, then alternate order across replicates.
    pairs = []
    for replicate in range(3):
        ordered = sorted(ids, key=lambda task: sha(f'{SEED}:{replicate}:{task}'.encode()))
        for index, task_id in enumerate(ordered):
            order = STRATEGY_IDS if (index + replicate) % 2 == 0 else STRATEGY_IDS[::-1]
            for strategy_id in order:
                pairs.append({'replicate': replicate + 1, 'task_id': task_id, 'strategy_id': strategy_id})
    return pairs


def paths(root):
    return root/'.ascendra'/STUDY, root/'benchmarks'/BENCHMARK


def prepare(root):
    study, benchmark = paths(root)
    if (study/'preregistration.json').exists():
        return verify_preregistration(root)
    raw = (root/'.ascendra/research-source/HumanEval.jsonl.gz').read_bytes()
    if sha(raw) != SOURCE_SHA256:
        raise ValueError('External source hash mismatch; refusing partial or substituted benchmark.')
    rows = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
    if len(rows) != 164 or len({r['task_id'] for r in rows}) != 164:
        raise ValueError('Unexpected source dataset grain.')
    ids = selected_ids([r['task_id'] for r in rows])
    study.mkdir(parents=True, exist_ok=True)
    benchmark.mkdir(parents=True, exist_ok=True)
    tasks = []
    for row in rows:
        if row['task_id'] not in ids:
            continue
        task_id = row['task_id'].replace('/', '_')
        task = benchmark/'tasks'/task_id
        private = task/'.ascendra_hidden'
        private.mkdir(parents=True, exist_ok=True)
        stub = row['prompt'] + '    raise NotImplementedError\n'
        reference = row['prompt'] + row['canonical_solution']
        compile(stub, 'task.py', 'exec')
        compile(reference, 'reference.py', 'exec')
        (task/'task.py').write_text(stub)
        (private/'reference.py').write_text(reference)
        # Trusted wrapper runs in a separate OS sandbox with no host files or network.
        wrapper = (
            'import os, resource\n'
            'resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))\n'
            'resource.setrlimit(resource.RLIMIT_CPU, (10, 10))\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))\n'
            'namespace = {}\n'
            "with open('/task/task.py') as source: candidate = source.read()\n"
            "exec(compile(candidate, 'task.py', 'exec'), namespace)\n"
            f"exec(compile({row['test']!r}, 'private_evaluator', 'exec'), namespace)\n"
            f"namespace['check'](namespace[{row['entry_point']!r}])\n"
            f"print({PASS_MARKER!r}, flush=True)\n"
        )
        (private/'check.py').write_text(wrapper)
        tasks.append({'id':task_id, 'upstream_id':row['task_id'],
                      'description':'Complete the function according to the public task.py specification. Preserve its signature.',
                      'split':'holdout', 'eval_group':1, 'timeout_s':15,
                      'hidden_globs':['.ascendra_hidden/**'],
                      'test_command':['python3','-I','/task/.ascendra_hidden/check.py']})
    tasks.sort(key=lambda t:ids.index(t['upstream_id']))
    (benchmark/'manifest.json').write_text(json.dumps({'tasks':tasks},indent=2)+'\n')
    with sqlite3.connect(root/'.ascendra/evidence.db') as db:
        db.row_factory = sqlite3.Row
        strategies = [dict(db.execute('SELECT * FROM strategies WHERE id=?',(sid,)).fetchone()) for sid in STRATEGY_IDS]
    for strategy in strategies:
        strategy['metadata'] = json.loads(strategy['metadata'])
        if sha(strategy['prompt'].encode()) != strategy['metadata']['prompt_sha256']:
            raise ValueError('Frozen strategy hash mismatch.')
    (study/'strategies.json').write_text(json.dumps(strategies,indent=2)+'\n')
    monitored = sorted(root.glob('ascendra/*.py')) + sorted(root.glob('tests/*.py'))
    monitored += [root/'run_external_research.sh',root/'EXTERNAL_RESEARCH.md']
    monitored += sorted(p for p in benchmark.rglob('*') if p.is_file())
    monitored += [study/'strategies.json']
    registration = {
        'study':STUDY, 'registered_at':time.time(), 'seed':SEED,
        'source_repository':'https://github.com/openai/human-eval', 'source_commit':SOURCE_COMMIT,
        'source_sha256':SOURCE_SHA256, 'upstream_ids':ids,
        'provider':'codex_subscription', 'model_requested':'gpt-6-astra', 'reasoning_effort':'low',
        'benchmark':BENCHMARK, 'task_count':20, 'replicates':3,
        'maximum_solve_calls':120, 'provider_timeout_s':180, 'evaluator_timeout_s':15,
        'strategy_ids':list(STRATEGY_IDS), 'schedule':schedule([t['id'] for t in tasks]),
        'primary_unit':'task; replicates are clustered within task',
        'decision_rule':'existing repeated gate IMPROVED, no task regression, and one-sided task-level sign-test p <= 0.05',
        'minimum_holdout_gain':0.05, 'task_level_alpha':0.05,
        'bootstrap_samples':10000, 'bootstrap_seed':20261003,
        'no_mutation':True, 'no_promotion_of_original_lineage':True,
        'stopping_rule':'all scheduled pairs; stop only for provider, isolation, integrity, or harness failure; no outcome-based retries or task replacement',
        'limitations':['public benchmark may have appeared in model training',
                       'function completion, not a repository engineering benchmark',
                       'independent replication within the same model/account; not an independent research team'],
        'files':{str(p.relative_to(root)):sha(p.read_bytes()) for p in monitored},
    }
    data = json.dumps(registration,indent=2,sort_keys=True)+'\n'
    with (study/'preregistration.json').open('x') as f:f.write(data)
    (study/'preregistration.sha256').write_text(sha(data.encode())+'\n')
    return registration


def verify_preregistration(root):
    study, _ = paths(root)
    raw = (study/'preregistration.json').read_bytes()
    if sha(raw) != (study/'preregistration.sha256').read_text().strip():
        raise ValueError('Preregistration was modified.')
    registration = json.loads(raw)
    for name, digest in registration['files'].items():
        if sha((root/name).read_bytes()) != digest:
            raise ValueError('Frozen study source or benchmark changed: '+name)
    return registration


class IsolatedEvaluatorSandbox(Sandbox):
    """Fresh read-only task mount, empty temp directory, no credentials or network."""
    def __init__(self, work_root):
        super().__init__(work_root)
        self.bwrap = shutil.which('bwrap')
        if not self.bwrap:raise ProviderBlocked('bubblewrap is required for isolated evaluation.')

    def command(self, workspace, command):
        if command != ['python3','-I','/task/.ascendra_hidden/check.py']:
            raise ProviderBlocked('External evaluator command differs from preregistered command.')
        cmd = [self.bwrap,'--die-with-parent','--unshare-all']
        for system in ('/usr','/lib','/lib64','/bin','/opt'):
            if Path(system).exists():cmd += ['--ro-bind',system,system]
        return cmd + ['--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                      '--ro-bind',str(workspace),'/task','--chdir','/task',
                      '--',sys.executable,'-I','/task/.ascendra_hidden/check.py']

    def run(self, cwd, command, timeout_s):
        start=time.monotonic()
        try:
            cp=subprocess.run(self.command(cwd,command),capture_output=True,text=True,timeout=timeout_s,
                              env={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'})
        except subprocess.TimeoutExpired:
            return 124,'','timeout',time.monotonic()-start
        if cp.returncode and cp.stderr.startswith('bwrap:'):
            raise ProviderBlocked('Evaluator OS isolation failed; not a candidate task failure.')
        rc=cp.returncode
        if rc == 0 and PASS_MARKER not in cp.stdout.splitlines():rc=125
        return rc,cp.stdout[-12000:],cp.stderr[-12000:],time.monotonic()-start


def validate_harness(root):
    verify_preregistration(root)
    study, benchmark=paths(root)
    sandbox=IsolatedEvaluatorSandbox(study/'validation-work')
    tasks=BenchmarkRegistry(benchmark).load()
    outcomes=[]
    for task in tasks:
        workspace=sandbox.create(task)
        try:
            stub_rc,*_=sandbox.run(workspace,task.test_command,task.timeout_s)
            # Reference contents remain evaluator-only and are never printed or prompted.
            shutil.copyfile(workspace/'.ascendra_hidden/reference.py',workspace/'task.py')
            reference_rc,*_=sandbox.run(workspace,task.test_command,task.timeout_s)
            outcomes.append({'task':task.id,'stub_failed':stub_rc!=0,'reference_passed':reference_rc==0})
        finally:sandbox.cleanup(workspace)
    report={'tasks':outcomes,'all_valid':all(r['stub_failed'] and r['reference_passed'] for r in outcomes)}
    (study/'harness-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['all_valid']:raise ProviderBlocked('External harness control failed; no tasks will be substituted.')
    return report


def sign_pvalue(wins,losses):
    n=wins+losses
    return sum(math.comb(n,k) for k in range(wins,n+1))/(2**n) if n else 1.0


def task_statistics(champions,candidates):
    old={};new={}
    for summary in champions:
        for r in summary.results:old[r.task_id]=old.get(r.task_id,0)+int(r.solved)
    for summary in candidates:
        for r in summary.results:new[r.task_id]=new.get(r.task_id,0)+int(r.solved)
    if set(old)!=set(new):raise ValueError('Unpaired task sets.')
    deltas=[(new[k]-old[k])/len(champions) for k in sorted(old)]
    wins=sum(x>0 for x in deltas);losses=sum(x<0 for x in deltas)
    rng=random.Random(20261003)
    bootstrap=sorted(sum(rng.choices(deltas,k=len(deltas)))/len(deltas) for _ in range(10000))
    return {'task_wins':wins,'task_losses':losses,'task_ties':len(deltas)-wins-losses,
            'one_sided_sign_p':sign_pvalue(wins,losses),
            'mean_pass_rate_difference':sum(deltas)/len(deltas),
            'task_bootstrap_95_interval':[bootstrap[249],bootstrap[9749]],
            'per_task':[{'task':k,'g0_passes':old[k],'g1_passes':new[k],'replicates':len(champions)} for k in sorted(old)]}


def aggregate(sid,results):
    solved=sum(r.solved for r in results)
    return EvalSummary(sid,len(results),solved,solved/len(results),0,0,len(results),solved,
                       sum(r.duration_s for r in results),results)


def run(root):
    registration=verify_preregistration(root)
    study,benchmark=paths(root)
    if (study/'evidence.db').exists():
        raise ProviderBlocked('Study evidence already exists. Outcome-based reruns are prohibited.')
    validation=validate_harness(root)
    provider=SubscriptionProvider(root=root,model=registration['model_requested'],effort=registration['reasoning_effort'])
    try:provider.preflight()
    finally:(study/'provider-preflight.json').write_text(json.dumps(provider.call_records,indent=2)+'\n')
    store=EvidenceStore(study/'evidence.db')
    provider.event_sink=store.event
    for record in provider.call_records:store.event('provider_call',record)
    strategies={}
    for row in json.loads((study/'strategies.json').read_text()):
        strategies[row['id']]=Strategy(row['id'],row['generation'],row['parent_id'],row['prompt'],row['metadata'])
        store.save_strategy(strategies[row['id']])
    tasks={t.id:t for t in BenchmarkRegistry(benchmark).load()}
    evaluator=Evaluator(IsolatedEvaluatorSandbox(study/'work'),EvolutionAgent(provider),store)
    grouped={(sid,rep):[] for sid in STRATEGY_IDS for rep in range(1,4)}
    store.event('external_experiment_started',{'preregistration_sha256':(study/'preregistration.sha256').read_text().strip(),
                                              'configuration':registration,'validation_passed':validation['all_valid']})
    start=time.monotonic()
    try:
        for index,item in enumerate(registration['schedule'],1):
            sid,rep,task_id=item['strategy_id'],item['replicate'],item['task_id']
            store.event('scheduled_evaluation',item)
            summary=evaluator.evaluate(strategies[sid],[tasks[task_id]])
            grouped[(sid,rep)].extend(summary.results)
            store.event('paired_observation',{**item,'solved':summary.results[0].solved,
                                              'returncode':summary.results[0].returncode})
            print(json.dumps({'finished':index,'planned':len(registration['schedule']),**item,
                              'solved':summary.results[0].solved}),flush=True)
        champions=[aggregate(STRATEGY_IDS[0],grouped[(STRATEGY_IDS[0],rep)]) for rep in range(1,4)]
        candidates=[aggregate(STRATEGY_IDS[1],grouped[(STRATEGY_IDS[1],rep)]) for rep in range(1,4)]
        decision=PromotionGate().decide_repeated(champions,candidates)
        clustered=task_statistics(champions,candidates)
        verified=decision.promote and clustered['one_sided_sign_p']<=registration['task_level_alpha']
        result={'status':'COMPLETED','verdict':'VERIFIED EXTERNAL GAIN' if verified else 'NO VERIFIED EXTERNAL GAIN',
                'framework_gate':asdict(decision),'task_statistics':clustered,
                'g0_solved':sum(s.solved for s in champions),'g1_solved':sum(s.solved for s in candidates),
                'total_per_strategy':60,'replicates':3,'tasks':20,
                'duration_s':time.monotonic()-start,'original_lineage_unchanged':True}
        verify_preregistration(root)
        store.event('external_experiment_completed',result)
        (study/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    except Exception as exc:
        store.event('external_experiment_blocked',{'error':str(exc),'duration_s':time.monotonic()-start})
        raise
    finally:
        (study/'evidence.json').write_text(json.dumps(store.export(),indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['prepare','validate','run'])
    parser.add_argument('--root',type=Path,default=Path.cwd())
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':
        result=prepare(root)
        print(json.dumps({'study':result['study'],'tasks':result['upstream_ids'],
                          'preregistration_sha256':(paths(root)[0]/'preregistration.sha256').read_text().strip()},indent=2))
    elif args.command=='validate':print(json.dumps(validate_harness(root),indent=2))
    else:print(json.dumps(run(root),indent=2))


if __name__=='__main__':main()
