"""Budget-matched workflow search and a sealed, disjoint confirmation experiment.

Private cases are decoded only by the grader; none are sent to the provider or
mounted into candidate processes. This is a local controlled LCB subset study,
not an official leaderboard submission or a promotion in the original lineage.
V2 excludes all prior registered tasks and allows only reviewed unique-output contracts.
"""
import argparse
import base64
import concurrent.futures
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zlib

from .subscription import ProviderBlocked, SubscriptionProvider

STUDY = 'method-search-lcb-v2'
SEED = 'ASCENDRA-' + STUDY
DATA_SHA = 'bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5'
DATA_REV = '0fe84c3912ea0c4d4a78037083943e8f0c4dd505'
ELIGIBLE_IDS = frozenset(['abc390_d', 'abc390_c', 'abc391_d', 'abc394_c', 'abc395_c', 'abc398_b', 'abc398_c', 'abc400_c', 'abc400_d', 'arc191_a', 'abc390_e', 'abc390_g', 'abc392_g', 'abc394_f', 'abc395_e', 'abc397_e', 'abc398_d', 'abc398_g', 'abc399_e', 'arc190_c', 'arc190_d', 'arc191_d', 'arc192_d', 'arc193_d', 'arc194_b', 'arc194_e', 'arc195_b', 'arc196_b', 'arc196_c', 'arc196_a', 'arc196_d'])
METHODS = ('best_of_two', 'public_repair', 'plan_then_code', 'critical_review')
BASE = ('Solve the supplied programming problem in Python 3 using only the standard library. '
        'Read stdin and write stdout. Derive an efficient algorithm from all stated constraints, '
        'check boundary cases, and return a complete executable program, without Markdown fences. '
        'Do not use tools. Work only from the public problem statement and examples.')
SCHEMA = {'type':'object','properties':{'content':{'type':'string'}},
          'required':['content'],'additionalProperties':False}
LOCK = threading.Lock()


def sha(data): return hashlib.sha256(data).hexdigest()
def dump(path, obj):
    with Path(path).open('x') as f: json.dump(obj,f,indent=2,sort_keys=True); f.write('\n')
def read(path): return json.loads(Path(path).read_text())
def where(root): return root/'.ascendra'/STUDY


class DataUnpickler(pickle.Unpickler):
    def find_class(self, module, name): raise ValueError('Non-data pickle is forbidden')


def decode_private(value):
    try: decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = json.loads(DataUnpickler(io.BytesIO(zlib.decompress(base64.b64decode(value)))).load())
    if not isinstance(decoded,list) or not decoded: raise ValueError('Invalid private cases')
    return decoded


def matches(actual, expected):
    # Pinned LCB stdin checker: strip whole text and each line, exact strings or exact
    # element-wise Decimal equality. No approximate float tolerance is added.
    lines = lambda text: [line.strip() for line in text.strip().split('\n')]
    a,b=lines(actual),lines(expected)
    if len(a)!=len(b): return False
    for x,y in zip(a,b):
        if x==y: continue
        try:
            if [Decimal(t) for t in x.split()] != [Decimal(t) for t in y.split()]: return False
        except (InvalidOperation,ValueError): return False
    return True


def splits(rows):
    result={'development':[],'confirmation':[]}
    for difficulty in ('medium','hard'):
        eligible=[r for r in rows if r['platform']=='atcoder' and r['difficulty']==difficulty and r['question_id'] in ELIGIBLE_IDS]
        ordered=sorted(eligible,key=lambda r:sha((SEED+':'+r['question_id']).encode()))
        if len(ordered)<9: raise ValueError('Insufficient eligible tasks')
        result['development'] += [r['question_id'] for r in ordered[:3]]
        result['confirmation'] += [r['question_id'] for r in ordered[3:9]]
    return result


def make_schedule(ids, methods, replicates):
    result=[]
    for rep in range(1,replicates+1):
        tasks=sorted(ids,key=lambda t:sha(f'{SEED}:{rep}:{t}'.encode()))
        for i,task in enumerate(tasks):
            shift=(i+rep-1)%len(methods)
            for method in methods[shift:]+methods[:shift]:
                result.append({'task':task,'method':method,'replicate':rep})
    return result


def prepare(root):
    study=where(root)
    if (study/'preregistration.json').exists(): return verify(root)
    raw=(root/'.ascendra/lcb-source/test6.jsonl').read_bytes()
    if sha(raw)!=DATA_SHA: raise ValueError('Dataset fingerprint mismatch')
    rows=[json.loads(line) for line in raw.splitlines()]
    selected=splits(rows); ids=sum(selected.values(),[])
    if len(set(ids))!=18: raise ValueError('Overlapping task splits')
    tasks=study/'tasks'; tasks.mkdir(parents=True,exist_ok=True)
    metadata=[]
    for r in rows:
        if r['question_id'] not in ids: continue
        task=tasks/r['question_id']; (task/'.ascendra_hidden').mkdir(parents=True)
        public=json.loads(r['public_test_cases']); private=decode_private(r['private_test_cases'])
        for case in public+private:
            if not {'input','output'} <= set(case) or not all(isinstance(case[k],str) for k in ('input','output')):
                raise ValueError('Unsupported testcase format')
            if case.get('testtype') != 'stdin': raise ValueError('Only stdin tasks are eligible')
        dump(task/'public.json',{'task_id':r['question_id'],'statement':r['question_content'],
                                'examples':public,'difficulty':r['difficulty'],'date':r['contest_date']})
        dump(task/'.ascendra_hidden/cases.json',private)
        metadata.append({'task':r['question_id'],'difficulty':r['difficulty'],
                         'public_cases':len(public),'private_cases':len(private)})
    monitored=[root/'ascendra/method_research_v2.py',root/'METHOD_ELIGIBILITY.json',root/'tests/test_method_research_v2.py',root/'ascendra/subscription.py',
               root/'ascendra/provider.py',root/'ascendra/agent.py',
               root/'tests/test_method_research.py',root/'METHOD_RESEARCH_V2.md',root/'run_method_research_v2.sh']
    monitored+=sorted(p for p in tasks.rglob('*') if p.is_file())
    registration={'study':STUDY,'registered_at':time.time(),'seed':SEED,
        'dataset':'livecodebench/code_generation_lite','dataset_revision':DATA_REV,'dataset_file':'test6.jsonl',
        'dataset_sha256':DATA_SHA,'task_metadata':metadata,'splits':selected,
        'eligibility_review':read(root/'METHOD_ELIGIBILITY.json'),'prior_study_invalidated':'method-search-lcb-v1',
        'model_requested':'gpt-6-astra','reasoning_effort':'low','provider':'codex_subscription',
        'methods':list(METHODS),'base_instruction':BASE,'calls_per_trial':2,'workers':2,
        'development_replicates':1,'confirmation_replicates':3,'maximum_experimental_calls':192,
        'development_schedule':make_schedule(selected['development'],list(METHODS),1),
        'selection':'Rank the three nonbaseline methods by dev fully solved count, then selected public passes, then METHODS order. Freeze the highest-ranked method even if below baseline.',
        'candidate_selection':'For methods with two programs, most passing public cases; ties choose the second. Plan method has one program.',
        'confirmation_schedule_template':make_schedule(selected['confirmation'],['best_of_two','WINNER'],3),
        'primary_unit':'task, with three paired replicates clustered within task',
        'verification_gate':'positive pass-rate difference >= 0.05, no aggregate task regression, one-sided task sign p <= 0.05, paired Wilson lower bound > 0.5',
        'case_cpu_seconds':6,'case_wall_seconds':8,'suite_wall_seconds':180,
        'candidate_memory_bytes':536870912,'output_limit_bytes':1048576,'provider_timeout_seconds':180,
        'stopping':'Run full fixed schedule; no outcome-based retries or replacement. Provider, integrity or harness failures stop the study. Interrupted in-flight calls may not be repeated.',
        'claim_limits':['public problems may occur in training','only 6 dev and 12 confirmation tasks',
                        'two model calls do not mean identical token compute','custom isolated Python stdin runner, not official leaderboard',
                        'no weight training and no promotion in original G0-G1-G2 lineage',
                        'no canonical solutions supplied by this dataset; harness validated with independent synthetic fixtures'],
        'files':{str(p.relative_to(root)):sha(p.read_bytes()) for p in monitored}}
    dump(study/'preregistration.json',registration)
    (study/'preregistration.sha256').write_text(sha((study/'preregistration.json').read_bytes())+'\n')
    return registration


def verify(root):
    study=where(root); raw=(study/'preregistration.json').read_bytes()
    if sha(raw)!=(study/'preregistration.sha256').read_text().strip(): raise ValueError('Modified preregistration')
    reg=json.loads(raw)
    for name,digest in reg['files'].items():
        if sha((root/name).read_bytes())!=digest: raise ValueError('Frozen file changed: '+name)
    return reg


def sandbox_command(directory):
    # A project-local virtualenv is intentionally not mounted into the sandbox.
    interpreter=str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
    cmd=[shutil.which('bwrap') or 'bwrap','--die-with-parent','--unshare-all']
    for path in ('/usr','/lib','/lib64','/bin','/opt'):
        if Path(path).exists(): cmd+=['--ro-bind',path,path]
    return cmd+['--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                '--ro-bind',str(directory),'/task','--chdir','/task','--',interpreter,'-I','/task/runner.py']


RUNNER = """import resource, runpy
resource.setrlimit(resource.RLIMIT_AS, (536870912,536870912))
resource.setrlimit(resource.RLIMIT_CPU, (6,6))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576,1048576))
resource.setrlimit(resource.RLIMIT_NPROC, (32,32))
runpy.run_path('/task/main.py',run_name='__main__')
"""


def evaluate(code, cases, *, public=False, stop_first=False):
    start=time.monotonic(); results=[]
    with tempfile.TemporaryDirectory(prefix='ascendra-lcb-run-') as td:
        directory=Path(td); (directory/'main.py').write_text(code); (directory/'runner.py').write_text(RUNNER)
        for case in cases:
            if time.monotonic()-start>180:
                results.append({'passed':False,'status':'suite_timeout'}); break
            # Expected outputs never enter the candidate filesystem or stdin.
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                try:
                    cp=subprocess.run(sandbox_command(directory),input=case['input'].encode(),stdout=out,stderr=err,
                        timeout=min(8,max(0.1,180-(time.monotonic()-start))),env={'PATH':'/usr/bin:/bin'})
                    out.seek(0); actual=out.read(1048577).decode(errors='replace')
                    err.seek(0); error=err.read(4000).decode(errors='replace')
                    if cp.returncode and error.startswith('bwrap:'): raise ProviderBlocked('Candidate OS isolation failed')
                    passed=cp.returncode==0 and len(actual.encode())<=1048576 and matches(actual,case['output'])
                    status='pass' if passed else ('runtime_error' if cp.returncode else 'wrong_answer')
                except subprocess.TimeoutExpired:
                    actual=''; error=''; passed=False; status='timeout'
            item={'passed':passed,'status':status}
            if public: item.update({'input':case['input'],'expected':case['output'],
                                    'actual':actual[:3000],'stderr':error[:1500]})
            results.append(item)
            if stop_first and not passed: break
    return {'solved':len(results)==len(cases) and all(x['passed'] for x in results),
            'passed':sum(x['passed'] for x in results),'executed':len(results),'total':len(cases),
            'duration_s':time.monotonic()-start,'results':results}


def pick_program(programs, public_scores):
    if len(programs)!=len(public_scores) or not programs: raise ValueError('Unpaired programs/scores')
    return max(range(len(programs)),key=lambda i:(public_scores[i]['passed'],i))


def request_for(task, instruction, **extra):
    # This explicit allowlist is the entire provider snapshot.
    return {'instruction':instruction,'task_id':task['task_id'],'public_files':{'problem.txt':task['statement']},
            'public_examples':task['examples'],**extra}


def controller(task, method, call, grader=evaluate):
    if method not in METHODS: raise ValueError('Unknown method')
    programs=[]; scores=[]
    if method=='plan_then_code':
        plan=call(1,request_for(task,'Develop a precise algorithm and complexity argument for the supplied programming problem. '
            'Check boundary cases and all stated constraints. Target Python 3 standard library, stdin and stdout. '
            'Return the plan only, no program. Do not use tools. Work only from the supplied public information.'))
        code=call(2,request_for(task,BASE+' Implement the following proposed plan, correcting flaws if necessary.',plan=plan))
        programs.append(code); scores.append(grader(code,task['examples'],public=True))
    else:
        first=call(1,request_for(task,BASE)); programs.append(first)
        scores.append(grader(first,task['examples'],public=True))
        if method=='best_of_two': second_request=request_for(task,BASE)
        elif method=='public_repair':
            second_request=request_for(task,BASE+' Review and improve the previous program using the public test feedback. '
                'If all examples pass, verify asymptotic complexity and edge cases and preserve correct behavior.',
                previous_program=first,public_feedback=scores[0])
        else:
            second_request=request_for(task,BASE+' Critically review the proposed program for algorithmic counterexamples, '
                'boundary errors and complexity violations. Correct any flaws, or return it unchanged if justified.',
                previous_program=first)
        second=call(2,second_request); programs.append(second)
        scores.append(grader(second,task['examples'],public=True))
    chosen=pick_program(programs,scores)
    return programs[chosen],{'selected_index':chosen,'public_scores':scores,
                            'program_hashes':[sha(p.encode()) for p in programs]}


def append_event(path, obj):
    with LOCK:
        with path.open('a') as f: f.write(json.dumps(obj,sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())


def trial(root, phase, spec):
    study=where(root); task=read(study/'tasks'/spec['task']/'public.json')
    directory=study/'trials'/phase/f"{spec['task']}__{spec['method']}__r{spec['replicate']}"
    if (directory/'result.json').exists(): return read(directory/'result.json')
    directory.mkdir(parents=True,exist_ok=True)
    provider=SubscriptionProvider(root=root,timeout_s=180)
    active={'stage':0}
    def sink(kind, record):
        append_event(study/'provider-events.jsonl',{'phase':phase,**spec,'stage':active['stage'],'kind':kind,**record})
    provider.event_sink=sink
    def call(stage,request):
        active['stage']=stage
        response=directory/f'call-{stage}-response.json'; request_file=directory/f'call-{stage}-request.json'
        if response.exists(): return read(response)['content']
        if request_file.exists(): raise ProviderBlocked('Interrupted in-flight call; refusing an outcome-based retry')
        dump(request_file,request)
        result=provider._exec(json.dumps(request),SCHEMA)
        if set(result)!={'content'} or not isinstance(result['content'],str) or len(result['content'])>100000:
            raise ProviderBlocked('Invalid or oversized structured response')
        dump(response,result)
        return result['content']
    start=time.monotonic()
    if (directory/'selection.json').exists():
        selection=read(directory/'selection.json'); code=(directory/'selected.py').read_text()
        if sha(code.encode())!=selection['program_hashes'][selection['selected_index']]:
            raise ValueError('Modified selected program')
    else:
        code,selection=controller(task,spec['method'],call)
        (directory/'selected.py').write_text(code)
        # Selection is frozen on public data before the private evaluator is opened.
        dump(directory/'selection.json',selection)
    private=read(study/'tasks'/spec['task']/'.ascendra_hidden/cases.json')
    evaluation=evaluate(code,private,stop_first=True)
    result={'phase':phase,**spec,'solved':evaluation['solved'] and selection['public_scores'][selection['selected_index']]['solved'],
            'private_evaluation':evaluation,'selected_public_passes':selection['public_scores'][selection['selected_index']]['passed'],
            'selected_sha256':sha(code.encode()),'duration_s':time.monotonic()-start}
    dump(directory/'result.json',result)
    print(json.dumps({'event':'trial_complete',**spec,'phase':phase,'solved':result['solved']}),flush=True)
    return result


def choose_winner(results):
    rankings=[]
    for method in METHODS:
        subset=[r for r in results if r['method']==method]
        rankings.append({'method':method,'solved':sum(r['solved'] for r in subset),
                         'total':len(subset),'public_passes':sum(r['selected_public_passes'] for r in subset)})
    challengers=[r for r in rankings if r['method']!='best_of_two']
    winner=max(challengers,key=lambda r:(r['solved'],r['public_passes'],-METHODS.index(r['method'])))['method']
    return winner,rankings


def statistics(results,winner):
    pairs={}
    for r in results: pairs.setdefault((r['task'],r['replicate']),{})[r['method']]=int(r['solved'])
    if not pairs or any(set(p)!={'best_of_two',winner} for p in pairs.values()): raise ValueError('Incomplete pairs')
    deltas=[p[winner]-p['best_of_two'] for p in pairs.values()]
    gains=sum(x>0 for x in deltas); losses=sum(x<0 for x in deltas); n=gains+losses
    z=1.959963984540054
    lower=((gains/n+z*z/(2*n)-z*math.sqrt((gains/n)*(1-gains/n)/n+z*z/(4*n*n)))/(1+z*z/n)) if n else 0
    tasks={}
    for (task,rep),p in pairs.items():
        item=tasks.setdefault(task,{'baseline':0,'candidate':0,'replicates':0})
        item['baseline']+=p['best_of_two']; item['candidate']+=p[winner]; item['replicates']+=1
    wins=sum(p['candidate']>p['baseline'] for p in tasks.values())
    regressions=sum(p['candidate']<p['baseline'] for p in tasks.values())
    discordant=wins+regressions
    pvalue=sum(math.comb(discordant,k) for k in range(wins,discordant+1))/(2**discordant) if discordant else 1.0
    gain=sum(deltas)/len(deltas)
    improved=gain>=.05 and regressions==0 and pvalue<=.05 and lower>.5
    return {'winner':winner,'baseline_solved':sum(p['best_of_two'] for p in pairs.values()),
        'candidate_solved':sum(p[winner] for p in pairs.values()),'paired_trials':len(pairs),
        'paired_gains':gains,'paired_losses':losses,'paired_ties':len(pairs)-n,'paired_wilson_lower':lower,
        'task_wins':wins,'task_regressions':regressions,'task_ties':len(tasks)-discordant,'task_sign_p':pvalue,
        'pass_rate_difference':gain,'per_task':tasks,'verdict':'VERIFIED WORKFLOW GAIN' if improved else 'NO VERIFIED IMPROVEMENT',
        'original_lineage_promoted':False}


def run_phase(root,phase,schedule):
    results=[]
    # A pair's two methods may overlap; order is rotated and concurrency is fixed.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending={}; iterator=iter(schedule)
        for _ in range(2):
            spec=next(iterator,None)
            if spec: pending[pool.submit(trial,root,phase,spec)]=spec
        while pending:
            done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                pending.pop(future); results.append(future.result())
                spec=next(iterator,None)
                if spec: pending[pool.submit(trial,root,phase,spec)]=spec
    return results


def run(root):
    reg=verify(root); study=where(root); start=time.monotonic()
    if (study/'summary.json').exists(): return read(study/'summary.json')
    if not (study/'preflight.json').exists():
        provider=SubscriptionProvider(root=root)
        provider.event_sink=lambda kind,record:append_event(study/'provider-events.jsonl',{'phase':'preflight','kind':kind,**record})
        dump(study/'preflight.json',provider.preflight())
    dev=run_phase(root,'development',reg['development_schedule'])
    winner,ranking=choose_winner(dev)
    freeze={'winner':winner,'development_ranking':ranking,'source_preregistration_sha256':sha((study/'preregistration.json').read_bytes()),
            'development_results':{str(p.relative_to(study)):sha(p.read_bytes()) for p in sorted((study/'trials/development').glob('*/result.json'))}}
    if (study/'winner-freeze.json').exists():
        if read(study/'winner-freeze.json')!=freeze: raise ValueError('Modified selection')
    else:
        dump(study/'winner-freeze.json',freeze)
        (study/'winner-freeze.sha256').write_text(sha((study/'winner-freeze.json').read_bytes())+'\n')
    print(json.dumps({'event':'winner_frozen','winner':winner,'ranking':ranking}),flush=True)
    schedule=[{**s,'method':winner if s['method']=='WINNER' else s['method']} for s in reg['confirmation_schedule_template']]
    confirm=run_phase(root,'confirmation',schedule)
    verify(root)
    events=[json.loads(l) for l in (study/'provider-events.jsonl').read_text().splitlines()]
    summary={'study':STUDY,'development':ranking,'confirmation':statistics(confirm,winner),
        'resources':{'calls':len(events),'input_tokens':sum(e.get('input_tokens') or 0 for e in events),
            'output_tokens':sum(e.get('output_tokens') or 0 for e in events),
            'total_tokens':sum(e.get('total_tokens') or 0 for e in events),
            'provider_errors':sum(e['status']!='completed' for e in events),'tool_calls':sum(e['tool_calls'] for e in events),
            'run_wall_seconds':time.monotonic()-start,'summed_provider_seconds':sum(e['duration_s'] for e in events),'measured_cost':None},
        'preregistration_sha256':sha((study/'preregistration.json').read_bytes()),
        'winner_freeze_sha256':sha((study/'winner-freeze.json').read_bytes()),'limitations':reg['claim_limits']}
    dump(study/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['prepare','verify','run'])
    args=parser.parse_args(); root=Path.cwd()
    result={'prepare':prepare,'verify':verify,'run':run}[args.action](root)
    if args.action!='run': result={k:result[k] for k in ('study','splits','maximum_experimental_calls')}
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
