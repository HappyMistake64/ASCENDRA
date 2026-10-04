"""Independent, evaluator-owned checks for declarative learned capabilities.

Verification means that the workflow actually observes source and executes tests
with the right public inputs. It does not certify semantic bug diagnosis, bug
repair, or a general ability to invent tools. Fixtures are created only after a
concrete workflow spec is supplied. No provider calls are made here.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile

VERIFIER_VERSION = 'capability-evaluator-v1'
_INPUTS = ('source_path', 'test_dir', 'test_pattern', 'query')
_ALLOWED_TOOLS = frozenset(('list_files', 'read_file', 'search_text', 'run_tests'))
_INPUT_SCHEMA = {'type':'object','properties':{key:{'type':'string'} for key in _INPUTS},
                 'required':list(_INPUTS),'additionalProperties':False}
CONTRACTS = {
    'python_test_diagnosis': {
        'contract_id':'python_test_diagnosis',
        'description':'Inspect the supplied Python source, search for the supplied query, and run the supplied test discovery directory/pattern. Preserve actual counts and failing/error outcomes; an executed failing suite is a successful diagnostic observation, not a passing project.',
        'input_schema':copy.deepcopy(_INPUT_SCHEMA),
        'allowed_tools':sorted(_ALLOWED_TOOLS),
        'required_steps':[
            {'tool':'read_file','arguments':{'path':'$input.source_path'}},
            {'tool':'search_text','arguments':{'query':'$input.query'}},
            {'tool':'run_tests','arguments':{'start_dir':'$input.test_dir','pattern':'$input.test_pattern'}}],
        'verification_scope':'Actual source/search/test observations on independent fixture variations. Does not verify explanatory reasoning or bug repair.',
    },
    'python_project_inspection': {
        'contract_id':'python_project_inspection',
        'description':'Inspect a Python project using actual source reading, search, and parameterized unittest discovery, preserving pass/failure/error observations.',
        'input_schema':copy.deepcopy(_INPUT_SCHEMA),
        'allowed_tools':sorted(_ALLOWED_TOOLS),
        'required_steps':[
            {'tool':'read_file','arguments':{'path':'$input.source_path'}},
            {'tool':'search_text','arguments':{'query':'$input.query'}},
            {'tool':'run_tests','arguments':{'start_dir':'$input.test_dir','pattern':'$input.test_pattern'}}],
        'verification_scope':'Same bounded operational inspection checks as python_test_diagnosis; no repair or semantic-diagnosis claim.',
    },
}


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def _check(ok,message):
    if not ok:raise ValueError(message)


def _validate_spec(spec):
    _check(isinstance(spec,dict),'Capability spec must be an object')
    _check(isinstance(spec.get('contract_id'),str),'Missing contract_id')
    schema=spec.get('input_schema',{})
    _check(isinstance(schema,dict) and schema.get('type')=='object','Missing object input schema')
    properties=schema.get('properties',{});required=schema.get('required',[])
    _check(isinstance(properties,dict) and isinstance(required,list),'Invalid input schema')
    for name in _INPUTS:
        _check(properties.get(name)=={'type':'string'} and name in required,'Contract input must be required string: '+name)
    _check(set(properties)==set(_INPUTS) and set(required)==set(_INPUTS),'Unsupported contract inputs')
    _check(schema.get('additionalProperties') is False,'Contract rejects extra inputs')
    steps=spec.get('steps');_check(isinstance(steps,list) and 3<=len(steps)<=16,'Expected 3 to 16 tool steps')
    counts={name:0 for name in _ALLOWED_TOOLS}
    for step in steps:
        _check(isinstance(step,dict) and set(step)=={'tool','arguments'},'Malformed tool step')
        name,args=step['tool'],step['arguments']
        _check(isinstance(name,str) and name in _ALLOWED_TOOLS,'Tool not allowed by inspection contract')
        _check(isinstance(args,dict),'Tool arguments must be an object');counts[name]+=1
        expected_keys={'list_files':{'path'},'read_file':{'path'},'search_text':{'query','path'},'run_tests':{'start_dir','pattern'}}[name]
        _check(set(args)<=expected_keys,'Unexpected tool arguments')
        for key,value in args.items():
            _check(isinstance(value,str),'Inspection tool arguments must be strings')
            if '$' in value:_check(value in {'$input.'+field for field in _INPUTS},'Only whole contract-input templates are supported')
    expected=CONTRACTS[spec['contract_id']]['required_steps']
    for mandatory in expected:
        _check(any(step['tool']==mandatory['tool'] and all(step['arguments'].get(k)==v for k,v in mandatory['arguments'].items()) for step in steps),'Missing parameterized '+mandatory['tool']+' step')
    _check(counts['run_tests']==1,'Contract requires exactly one authoritative test run')


def _fixture(index,spec_hash):
    tag=hashlib.sha256((VERIFIER_VERSION+':'+spec_hash+':'+str(index)).encode()).hexdigest()[:12]
    module_dir='unit_'+tag[:4];module_name='logic_'+tag[4:8]
    source_path=module_dir+'/'+module_name+'.py'
    test_dir=('checks_'+tag[8:]) if index==0 else ('verify_'+tag[:4]+'/nested_'+tag[4:8])
    pattern='probe_'+tag[8:]+'*.py';query='inspection_marker_'+tag
    if index==0:
        implementation='    return value * 2\n';examples=[(0,0),(7,14)];expected={'tests_run':2,'failures':0,'errors':0,'successful':True}
    elif index==1:
        implementation='    return 7 if value == 3 else value * 2\n';examples=[(0,0),(2,4),(3,6)];expected={'tests_run':3,'failures':1,'errors':0,'successful':False}
    else:
        implementation='    if value < 0:\n        raise ValueError("fixture negative boundary")\n    return value * 2\n';examples=[(-1,-2),(0,0),(1,2),(2,4)];expected={'tests_run':4,'failures':0,'errors':1,'successful':False}
    source='# '+query+'\ndef transform(value):\n'+implementation
    parent_depth=len(Path(test_dir).parts)
    tests='import importlib.util\nfrom pathlib import Path\nimport unittest\n'
    tests+=f'_source = Path(__file__).resolve().parents[{parent_depth}] / {source_path!r}\n'
    tests+='_spec = importlib.util.spec_from_file_location("fixture_subject", _source)\n_subject = importlib.util.module_from_spec(_spec)\n_spec.loader.exec_module(_subject)\n\nclass IndependentChecks(unittest.TestCase):\n'
    for number,(value,result) in enumerate(examples):
        tests+=f'    def test_case_{number}(self):\n        self.assertEqual(_subject.transform({value!r}), {result!r})\n'
    files={source_path:source,test_dir+'/probe_'+tag[8:]+'.py':tests}
    # Make nested discovery directories importable without relying on sys.path.
    for path in (Path(module_dir),Path(test_dir)):
        for count in range(1,len(path.parts)+1):files[str(Path(*path.parts[:count])/'__init__.py')]=''
    inputs={'source_path':source_path,'test_dir':test_dir,'test_pattern':pattern,'query':query}
    return {'id':'fixture_'+tag,'files':files,'inputs':inputs,'expected':expected}


class _RecordingCatalog:
    """Capture actual trusted tool executions; ignore a workflow's claimed trace."""
    def __init__(self,catalog):self._catalog=catalog;self.events=[]
    def descriptors(self):return self._catalog.descriptors()
    def execute(self,name,arguments):
        _check(name in _ALLOWED_TOOLS,'Evaluator forbids mutating or unknown tools')
        result=self._catalog.execute(name,arguments)
        self.events.append({'tool':name,'arguments':copy.deepcopy(arguments),'result':copy.deepcopy(result)})
        return result
    def __getattr__(self,name):return getattr(self._catalog,name)


def _observations(events,inputs,expected,source_text):
    tests=[event for event in events if event['tool']=='run_tests']
    reads=[event for event in events if event['tool']=='read_file' and event['arguments'].get('path')==inputs['source_path']]
    searches=[event for event in events if event['tool']=='search_text' and event['arguments'].get('query')==inputs['query']]
    source_hash=hashlib.sha256(source_text.encode()).hexdigest()
    def valid_read(event):
        result=event['result'];data=result.get('data',{})
        return result.get('status')=='ok' and isinstance(data,dict) and data.get('content')==source_text and data.get('sha256')==source_hash and data.get('truncated') is False
    def valid_search(event):
        result=event['result'];data=result.get('data',{})
        if result.get('status')!='ok' or not isinstance(data,dict):return False
        matches=data.get('matches',[])
        return isinstance(matches,list) and any(isinstance(match,dict) and match.get('path')==inputs['source_path'] and inputs['query'] in match.get('text','') for match in matches)
    details={'source_read':bool(reads) and all(valid_read(e) for e in reads),
             'query_searched':bool(searches) and any(valid_search(e) for e in searches),
             'source_sha256':source_hash,
             'test_calls':len(tests),'observed':None,'expected':expected}
    okay=details['source_read'] and details['query_searched'] and len(tests)==1
    if len(tests)==1:
        event=tests[0];result=event['result'];data=result.get('data',{})
        counts={key:data.get(key) for key in ('tests_run','failures','errors','successful')} if isinstance(data,dict) else {}
        details['observed']=counts
        # bool is an int subclass: reject fake boolean counts explicitly.
        typed=all(type(counts.get(key)) is int for key in ('tests_run','failures','errors')) and type(counts.get('successful')) is bool
        okay=okay and result.get('status')=='ok' and typed and counts==expected and counts['tests_run']>0
        okay=okay and event['arguments'].get('start_dir')==inputs['test_dir'] and event['arguments'].get('pattern')==inputs['test_pattern']
    return bool(okay),details


def evaluate_capability(spec,catalog_factory=None):
    """Evaluate a frozen declarative spec using trusted real catalog execution.

    ``catalog_factory`` is a trusted injection seam for tests, never a model tool
    or a field accepted from a proposed spec. The default loads ToolCatalog.
    """
    try:spec_hash=_hash(spec)
    except (TypeError,ValueError):spec_hash=None
    declared_contract=spec.get('contract_id') if isinstance(spec,dict) else None
    contract=declared_contract if isinstance(declared_contract,str) and declared_contract.strip() else 'unregistered'
    evidence={'contract_id':contract,'verifier_version':VERIFIER_VERSION,'capability_sha256':spec_hash,
              'fixture_count':0,'fixtures':[],'results':[],'status':'needs_evaluation'}
    if contract not in CONTRACTS:
        evidence['reason']='No trusted evaluator exists for this capability contract.';return evidence
    if spec_hash is None:
        evidence.update(status='needs_evaluation',validation_error=True,reason='Capability spec is not finite JSON data.');return evidence
    try:_validate_spec(spec)
    except (TypeError,ValueError,KeyError) as exc:
        evidence.update(status='needs_evaluation',validation_error=True,reason=str(exc));return evidence
    if catalog_factory is None:
        from .capability_tools import ToolCatalog
        catalog_factory=ToolCatalog
    from .capability_agent import execute_workflow
    evidence['verification_scope']=CONTRACTS[contract]['verification_scope']
    for index in range(3):
        fixture=_fixture(index,spec_hash);inputs=fixture['inputs'];expected=fixture['expected']
        evidence['fixtures'].append({'id':fixture['id'],'input_sha256':_hash({'files':fixture['files'],'inputs':inputs}),'expected_sha256':_hash(expected)})
        with tempfile.TemporaryDirectory(prefix='ascendra-capability-eval-') as td:
            root=Path(td)
            for relative,content in fixture['files'].items():
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content)
            recorder=_RecordingCatalog(catalog_factory(root))
            try:
                execution=execute_workflow(copy.deepcopy(spec),copy.deepcopy(inputs),recorder,max_steps=16)
                passed,details=_observations(recorder.events,inputs,expected,fixture['files'][inputs['source_path']])
                _check(isinstance(execution,dict),'Invalid workflow execution result')
                passed=passed and execution.get('status')=='ok'
                details['execution_status']=execution.get('status')
                if execution.get('error'):details['execution_error']=str(execution['error'])[:1000]
            except Exception as exc:
                passed=False;details={'error_type':type(exc).__name__,'error':str(exc)[:1000]}
            evidence['results'].append({'fixture_id':fixture['id'],'passed':bool(passed),'actual_sha256':_hash(recorder.events),'details':details})
    evidence['fixture_count']=len(evidence['fixtures'])
    evidence['status']='verified' if len(evidence['results'])==3 and all(r['passed'] for r in evidence['results']) else 'failed'
    return evidence
