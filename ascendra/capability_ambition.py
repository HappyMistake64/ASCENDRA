"""Persistent, mission-bound ambitions with evidence-based milestone accounting.

Ambition is a planning policy, not a claim about feelings. Metric attainment is
scoped to trusted evaluator contracts; it is not proof of a goal's whole prose.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path

from .method_research_v4 import checked_json, freeze_json


_TEXT = {'type':'string'}
_GOAL = {'type':'object','additionalProperties':False,'properties':{
    'horizon':{'type':'string','enum':['now','next','stretch']},
    'title':_TEXT,'why':_TEXT,'next_step':_TEXT,
    'metric':{'type':'string','enum':['verified_objectives','verified_capabilities']},
    'contract_id':_TEXT,'target':{'type':'integer','minimum':1,'maximum':5}},
    'required':['horizon','title','why','next_step','metric','contract_id','target']}
AMBITION_SCHEMA = {'type':'object','additionalProperties':False,'properties':{
    'north_star':_TEXT,'goals':{'type':'array','items':_GOAL,'minItems':3,'maxItems':3}},
    'required':['north_star','goals']}


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class AmbitionBoard:
    def __init__(self, directory, mission):
        if not isinstance(mission,str) or not mission.strip() or len(mission)>8000:
            raise ValueError('Ambition needs a bounded user mission')
        self.mission=mission
        self.directory=Path(directory).resolve()
        self.root=self.directory/_hash(mission)[:24]
        self.root.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def _lock(self):
        with (self.root/'board.lock').open('a+') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    def _plans(self):
        plans=[checked_json(p) for p in sorted(self.root.glob('plan-*.json'))]
        for index,plan in enumerate(plans):
            if plan['mission']!=self.mission or plan['generation']!=index:
                raise ValueError('Ambition history is inconsistent')
        return plans

    def _assignments(self):
        return [checked_json(p) for p in sorted((self.root/'assignments').glob('*.json'))]

    def _context(self, store):
        plans=self._plans()
        if not plans:
            return dict(mission=self.mission,north_star=None,goals=[],active_goal=None,
                        generation=None,challenge_level=1)
        assignments=self._assignments()
        histories=[]
        attained=0
        for plan in plans:
            used=set(plan['baseline_capabilities'])
            goals=[]
            for goal in plan['goals']:
                ids=[a['episode_id'] for a in assignments if a['goal_id']==goal['id']]
                evidence=store.progress_evidence(ids)
                outcomes=[e for e in evidence['objectives'] if e['contract_id']==goal['contract_id']
                          and not e.get('infrastructure_error',False)]
                failures=sum(not e['success'] for e in outcomes)
                if goal['metric']=='verified_objectives':
                    credits=[e['episode_id'] for e in outcomes if e['success']]
                else:
                    credits=sorted({c['functional_sha256'] for c in evidence['capabilities']
                                    if c['contract_id']==goal['contract_id'] and c['status']=='verified'}-used)
                    used.update(credits)
                    failures=sum(c['status']=='failed' and c['contract_id']==goal['contract_id']
                                 for c in evidence['capabilities'])
                measured=len(credits)
                known=goal['contract_id'] in plan['contracts'].get(goal['metric'],[])
                if measured>=goal['target']:
                    status='metric_met';attained+=1
                elif not known:
                    status='needs_verifier'
                elif failures>=2 or (failures and len(ids)>=2):
                    status='needs_revision'
                elif len(ids)>=2 and not credits and not failures:
                    status='awaiting_evidence'
                else:
                    status='active'
                # One failed evaluation changes the next task before another attempt.
                mode='diagnose_and_reduce_scope' if failures else 'work_on_next_step'
                goals.append(dict(goal,measured=measured,credited_evidence=credits,
                    attempts=len(ids),failures=failures,status=status,next_action=mode))
            histories.append(dict(generation=plan['generation'],goals=goals))
        current=histories[-1]['goals']
        active=next((g for g in current if g['status']=='active'),None)
        return dict(mission=self.mission,north_star=plans[-1]['north_star'],generation=plans[-1]['generation'],
            goals=current,active_goal=active,challenge_level=min(5,1+attained),
            history=histories[:-1],progress_basis='Distinct trusted evidence assigned to this mission and milestone; metric attainment only',
            policy='User requests override ambitions. Choose useful learning within the mission and existing tools, permissions and budgets. After a failure, diagnose and reduce scope. Avoid repeated easy tasks; seek a justified new variation. Do not treat self-reports or test-tool success as mastery.')

    def context(self, store):
        with self._lock():
            return self._context(store)

    def ensure_plan(self, store, decide, contracts):
        """Create a bounded portfolio once, or refresh after all its metrics are met."""
        with self._lock():
            before=self._context(store)
            if before['goals'] and not all(g['status']=='metric_met' for g in before['goals']):
                return before
            request=dict(instruction=(
                'Design three useful long-term ambitions within the user mission, in horizons now, next, stretch. '
                'Explain each evidence gap, an actionable next step and a measurable target of 1..5 distinct '
                'verified outcomes or newly verified capabilities under a named evaluator contract. '
                'Prefer available contracts; an unknown contract requires a new trusted evaluator and cannot '
                'be credited yet. Build from observed weaknesses toward harder, genuinely different variations, '
                'not repeated trivial tasks or renamed copies of the same capability. Ambitions never override '
                'the user, permissions, stop commands or resource budgets. Do not seek self-preservation, '
                'privilege expansion or resources as goals. Describe useful engineering outcomes, not feelings. '
                'A metric being met does not prove the whole natural-language ambition. Return only the plan.'),
                mission=self.mission,learned_context=store.context(),previous_ambitions=before,
                available_progress_contracts=contracts)
            proposed=decide(request,AMBITION_SCHEMA)
            self._validate(proposed)
            generation=len(self._plans())
            plan=dict(proposed,mission=self.mission,generation=generation,contracts=contracts,
                baseline_capabilities=[_hash({key:c['spec'].get(key) for key in ('contract_id','input_schema','steps')})
                                       for c in store.list_capabilities(status='verified')])
            digest=_hash(plan)[:24]
            plan['goals']=[dict(g,id=digest+'-'+g['horizon']) for g in plan['goals']]
            freeze_json(self.root/f'plan-{generation:04d}.json',plan)
            return self._context(store)

    @staticmethod
    def _validate(plan):
        if not isinstance(plan,dict) or set(plan)!={'north_star','goals'}:
            raise ValueError('Invalid ambition plan fields')
        if not isinstance(plan['north_star'],str) or not plan['north_star'].strip() or len(plan['north_star'])>4000:
            raise ValueError('Invalid north star')
        goals=plan['goals']
        if not isinstance(goals,list) or len(goals)!=3:
            raise ValueError('Expected three ambition horizons')
        for horizon,goal in zip(('now','next','stretch'),goals):
            if not isinstance(goal,dict) or set(goal)!=set(_GOAL['required']) or goal['horizon']!=horizon:
                raise ValueError('Invalid ambition horizon or fields')
            if goal['metric'] not in ('verified_objectives','verified_capabilities'):
                raise ValueError('Unknown ambition metric')
            if type(goal['target']) is not int or not 1<=goal['target']<=5:
                raise ValueError('Invalid ambition target')
            for name in ('title','why','next_step','contract_id'):
                if not isinstance(goal[name],str) or not goal[name].strip() or len(goal[name])>4000:
                    raise ValueError('Ambition needs bounded nonempty text')

    def attach(self, episode_id, goal_id):
        """Bind a completed episode once; results still come only from ExperienceStore."""
        with self._lock():
            if goal_id not in {g['id'] for p in self._plans() for g in p['goals']}:
                raise ValueError('Unknown ambition goal')
            if not isinstance(episode_id,str) or not episode_id.startswith('episode_') or not episode_id[8:].isalnum():
                raise ValueError('Invalid episode identity')
            path=self.root/'assignments'/f'{episode_id}.json'
            record=dict(episode_id=episode_id,goal_id=goal_id)
            if path.exists():
                if checked_json(path)!=record:
                    raise ValueError('Episode already assigned to another ambition')
                return
            freeze_json(path,record)


def list_ambitions(directory, store):
    output=[]
    for first in sorted(Path(directory).glob('*/plan-0000.json')):
        mission=checked_json(first)['mission']
        output.append(AmbitionBoard(directory,mission).context(store))
    return output
