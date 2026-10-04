"""Real model-selected tools, persistent experience and independently checked workflows."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from .capability_agent import CapabilityAgent
from .capability_ambition import AmbitionBoard, list_ambitions
from .capability_evaluator import CONTRACTS, evaluate_capability
from .capability_memory import ExperienceStore
from .capability_tools import ToolCatalog
from .method_research_v4 import freeze_json
from .subscription import SubscriptionProvider
from .v4_ledger import FileLedger, ProviderFailure


def emit(event, **data):
    print(json.dumps(dict(event=event, **data), ensure_ascii=False), flush=True)


def _outside_project(project, location, label):
    project = Path(project).resolve(strict=True)
    location = Path(location).resolve()
    if location == project or project in location.parents:
        raise ValueError(label + ' must be outside the project directory')
    return location


class SubscriptionDecider:
    def __init__(self, output, *, model='gpt-6-astra', effort='low', max_calls=40, writable_paths=()):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.writable_paths = list(writable_paths)
        config = dict(model=model, effort=effort, max_calls=max_calls, version=1)
        freeze_json(self.output/'configuration.json', config)
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        self.ledger = FileLedger(self.output/'ledger', digest, dict(
            calls=max_calls, tokens=2_000_000, wall_seconds=7200,
            phase_caps={'planning':max_calls}, infra_retries=0,
            allow_infrastructure_retry=False, default_reserved_tokens=50000))
        self.provider = SubscriptionProvider(root=Path(__file__).resolve().parents[1],
                                             model=model, effort=effort, timeout_s=600)
        self.provider.verify_isolation()
        self.sequence = 0

    def __call__(self, request, schema):
        self.sequence += 1
        request = dict(request, public_files={}, available_verification_contracts=CONTRACTS,
            writable_paths=self.writable_paths,
            capability_policy=(
                'Choose your own tool sequence and useful reusable capabilities. Prefer an existing verified '
                'capability when it fits the current task. A proposed capability should generalize using '
                '$input.field placeholders and an explicit input_schema. The registered verification '
                'contracts describe what can be checked now; novel contracts are welcome as unverified '
                'research proposals. Do not duplicate an existing capability without a useful difference. '
                'Project test reports are observations, not independent proof. Modify only writable_paths. '
                'After completing the work, propose a useful capability or next research direction based '
                'on what you actually observed, if there is one. Never claim that weights were trained.'))
        envelope = dict(phase='planning', reserved_tokens=50000,
                        hard_token_limit_enforced=False, payload=request, schema=schema)
        def invoke(item):
            before = len(self.provider.call_records)
            try:
                result = self.provider._exec(json.dumps(item['payload']), item['schema'])
            except Exception as exc:
                usage = self.provider.call_records[-1] if len(self.provider.call_records)>before else None
                raise ProviderFailure(str(exc), usage=usage) from exc
            if len(self.provider.call_records) != before + 1:
                raise ProviderFailure('Provider did not record exactly one physical call', usage=None)
            usage = self.provider.call_records[-1]
            if (not isinstance(usage, dict) or usage.get('status') != 'completed'
                    or type(usage.get('tool_calls')) is not int or usage['tool_calls'] != 0):
                raise ProviderFailure('Provider returned invalid completion evidence',
                                      usage=usage if isinstance(usage, dict) else None)
            known_total = type(usage.get('total_tokens')) is int and usage['total_tokens'] >= 0
            known_parts = all(type(usage.get(k)) is int and usage[k] >= 0
                              for k in ('input_tokens', 'output_tokens'))
            if not known_total and not known_parts:
                raise ProviderFailure('Provider completion has no valid token usage', usage=usage)
            return result, usage
        emit('decision_started', call=self.sequence)
        result, usage = self.ledger.execute(f'decision-{self.sequence:04d}', envelope, invoke)
        emit('decision_complete', call=self.sequence, action=result.get('action','plan_ambitions' if 'goals' in result else 'choose_goal'),
             tool=result.get('tool'), tokens=usage.get('total_tokens'))
        return result


def run_episode(catalog, store, decide, goal, output, *, max_steps=14, mission=None, verifier=None, ambition=None):
    _outside_project(catalog.root, store.directory, 'Memory')
    output = _outside_project(catalog.root, output, 'Episode artifacts')
    output.mkdir(parents=True, exist_ok=True)
    ambition_before=None
    if ambition is not None:
        _outside_project(catalog.root, ambition.directory, 'Ambition memory')
        contracts={'verified_capabilities':list(CONTRACTS),'verified_objectives':[]}
        if verifier is not None:
            # The caller explicitly declares which objective contract it evaluates.
            contract=getattr(verifier,'contract_id',None)
            if contract:contracts['verified_objectives'].append(contract)
        ambition_before=ambition.ensure_plan(store,decide,contracts)
        freeze_json(output/'ambition_before.json',ambition_before)
        if goal is None and ambition_before['active_goal'] is None:
            summary=dict(episode_id=None,objective=None,stop_reason='ambition_waiting_for_evidence',
                         evaluations=[],selected_tools=[],ambition=ambition_before)
            freeze_json(output/'summary.json',summary)
            emit('ambition_paused',reason=summary['stop_reason'])
            return summary
    def guided_decide(request,schema):
        if ambition_before is not None:
            request=dict(request,ambition=ambition_before)
            request['instruction'] += (' Use the active ambition to choose a useful next step within the user mission. '
                'An explicit current goal takes priority. If next_action is diagnose_and_reduce_scope, '
                'select a smaller diagnostic task rather than blindly repeating the failed attempt. '
                'Ambitions do not change tool permissions or budgets.')
        return decide(request,schema)
    agent = CapabilityAgent(catalog, store, guided_decide, max_steps=max_steps,
                            max_proposals=min(2, max_steps), max_result_chars=12000)
    freeze_json(output/'context_before.json', store.context())
    if goal is None:
        choice = agent.choose_goal(mission or 'Improve this Python project and choose a useful next capability.')
        freeze_json(output/'chosen_goal.json', choice)
        goal = choice['goal']
        emit('goal_chosen', **choice)
    result = agent.run(goal)
    freeze_json(output/'episode.json', result)
    evaluations = []
    for identifier in result['proposal_ids']:
        spec = store.get_capability(identifier)['spec']
        evidence = evaluate_capability(spec)
        record = store.record_evaluation(identifier, evidence)
        evaluations.append(dict(id=identifier, evidence=evidence, status=record['status']))
        emit('capability_evaluated', id=identifier, status=record['status'],
             contract=evidence['contract_id'], fixtures=evidence['fixture_count'])
    objective = None
    if verifier is not None:
        objective = verifier()
        store.record_objective_outcome(result['episode_id'], objective['success'], objective)
        emit('objective_evaluated', success=objective['success'])
    summary = dict(episode_id=result['episode_id'], objective=objective,
                   stop_reason=result['stop_reason'], evaluations=evaluations,
                   selected_tools=[step['tool'] for step in result['steps'] if step['action']=='tool'])
    if ambition is not None:
        active=ambition_before['active_goal']
        if active is not None:
            ambition.attach(result['episode_id'],active['id'])
        summary['ambition']=ambition.context(store)
        freeze_json(output/'ambition_after.json',summary['ambition'])
    freeze_json(output/'summary.json', summary)
    freeze_json(output/'context_after.json', store.context())
    return summary


def create_demo_project(root, index):
    root.mkdir(parents=True)
    source, tests = ('calculator.py','tests') if index==1 else ('engine.py','checks')
    (root/tests).mkdir()
    (root/'README.md').write_text(
        f'The function mean(values) in {source} returns the arithmetic mean using true division. '
        'It accepts a nonempty list of finite numbers, including negative and fractional values. '
        f'An empty list must raise ValueError. Public unittest tests are in {tests}/.\n')
    (root/source).write_text('def mean(values):\n    return sum(values) // len(values)\n')
    (root/tests/'test_mean.py').write_text(
        f'import unittest\nfrom {source[:-3]} import mean\n\n'
        'class MeanChecks(unittest.TestCase):\n'
        '    def test_fractional_result(self):\n        self.assertEqual(mean([1, 2]), 1.5)\n'
        '    def test_whole_result(self):\n        self.assertEqual(mean([2, 4]), 3.0)\n')
    return source, tests


def demo(args):
    from .capability_objective import CONTRACT, verify_mean
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    store = ExperienceStore(output/'memory')
    ambition=AmbitionBoard(store.directory/'ambitions',
        'Develop reliable Python project inspection and arithmetic repair skills with verified progress.') if getattr(args,'ambition',True) else None
    decide = SubscriptionDecider(output/'provider', model=args.model, effort=args.effort,
                                  max_calls=2*args.max_steps+4)
    summaries = []
    for index in (1,2):
        project = output/f'project-{index}'
        source, tests = create_demo_project(project,index)
        decide.writable_paths = [source]
        catalog = ToolCatalog(project, writable_paths=[source])
        mission = (f'Inspect and repair the Python project according to README.md. Source is {source}; '
                   f'public tests are in {tests}/. Only {source} is writable. Choose your tools and a '
                   'useful reusable capability yourself, using prior experience if available. '
                   'Complete the repair and verify it using the available tools.')
        def objective_verifier():return verify_mean(project,source)
        objective_verifier.contract_id=CONTRACT
        summary = run_episode(catalog,store,decide,mission if index==1 else None,
            output/f'episode-{index}',max_steps=args.max_steps,mission=mission,
            verifier=objective_verifier,ambition=ambition)
        summaries.append(summary)
    result = dict(episodes=summaries, capabilities=store.list_capabilities(),
                  usage=decide.ledger.summary(), learning='persistent experience and verified workflows; no weight updates')
    freeze_json(output/'summary.json',result)
    emit('demo_complete', objectives=[x['objective']['success'] if x['objective'] else None for x in summaries],
         verified_capabilities=len(store.list_capabilities(status='verified')), usage=result['usage'])


def grow(args):
    project = Path(args.project).resolve(strict=True)
    memory = _outside_project(project, args.memory, 'Memory')
    # Keep experience, model traces and evaluator artifacts outside the model-visible project.
    output = _outside_project(project, memory/'runs'/uuid.uuid4().hex, 'Run artifacts')
    catalog = ToolCatalog(project,writable_paths=args.allow_write)
    store = ExperienceStore(memory)
    mission=args.goal or 'Inspect this Python project and choose a useful feasible improvement or learning goal.'
    ambition=AmbitionBoard(memory/'ambitions',mission) if getattr(args,'ambition',True) else None
    decide = SubscriptionDecider(output/'provider',model=args.model,effort=args.effort,
        max_calls=args.cycles*(args.max_steps+2),writable_paths=args.allow_write)
    summaries = []
    for index in range(args.cycles):
        summaries.append(run_episode(catalog,store,decide,args.goal if index==0 else None,
            output/f'episode-{index+1}',max_steps=args.max_steps,
            mission=mission,ambition=ambition))
        if summaries[-1]['stop_reason']=='ambition_waiting_for_evidence':break
    freeze_json(output/'summary.json',dict(episodes=summaries,usage=decide.ledger.summary()))
    emit('grow_complete', output=str(output), usage=decide.ledger.summary())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    demo_parser=commands.add_parser('demo')
    demo_parser.add_argument('--output',required=True)
    grow_parser=commands.add_parser('grow')
    grow_parser.add_argument('--project',required=True)
    grow_parser.add_argument('--memory',required=True)
    grow_parser.add_argument('--goal')
    grow_parser.add_argument('--allow-write',action='append',default=[])
    grow_parser.add_argument('--cycles',type=int,default=1,choices=range(1,11))
    for command in (demo_parser,grow_parser):
        command.add_argument('--no-ambition',dest='ambition',action='store_false',
                             help='Disable long-term ambition planning for this run')
        command.add_argument('--model',default='gpt-6-astra')
        command.add_argument('--effort',default='low',choices=('low','medium','high','xhigh'))
        command.add_argument('--max-steps',type=int,default=14,choices=range(1,33))
    status=commands.add_parser('status')
    status.add_argument('--memory',required=True)
    args=parser.parse_args(argv)
    if args.command=='demo':demo(args)
    elif args.command=='grow':grow(args)
    else:
        store=ExperienceStore(args.memory)
        print(json.dumps(dict(context=store.context(),capabilities=store.list_capabilities(),
                             ambitions=list_ambitions(store.directory/'ambitions',store)),indent=2))


if __name__=='__main__':
    main()
