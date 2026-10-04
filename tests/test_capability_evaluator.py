import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from ascendra.capability_evaluator import CONTRACTS,evaluate_capability
from ascendra.capability_tools import ToolCatalog


def valid_spec():
    contract=CONTRACTS['python_test_diagnosis']
    return {'name':'python_test_observer','description':'Inspect source and actual test results.',
            'motivation':'Use the same inspection on new project paths.',
            'contract_id':'python_test_diagnosis','input_schema':copy.deepcopy(contract['input_schema']),
            'steps':copy.deepcopy(contract['required_steps']),
            'success_criteria':'Read source, find query, observe actual nonempty test outcomes.'}


class CapabilityEvaluatorTests(unittest.TestCase):
    def test_real_independent_pass_failure_error_fixtures(self):
        spec=valid_spec();evidence=evaluate_capability(spec)
        self.assertEqual(evidence['status'],'verified')
        self.assertEqual(evidence['fixture_count'],3)
        self.assertEqual(len({f['id'] for f in evidence['fixtures']}),3)
        self.assertEqual([r['details']['observed']['tests_run'] for r in evidence['results']],[2,3,4])
        self.assertEqual([r['details']['observed']['successful'] for r in evidence['results']],[True,False,False])
        self.assertEqual([r['details']['observed']['failures'] for r in evidence['results']],[0,1,0])
        self.assertEqual([r['details']['observed']['errors'] for r in evidence['results']],[0,0,1])
        for result in evidence['results']:
            self.assertTrue(result['passed']);self.assertTrue(result['details']['source_read']);self.assertTrue(result['details']['query_searched'])
        expected=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
        self.assertEqual(evidence['capability_sha256'],expected)

    def test_unknown_contract_is_not_forged_verified(self):
        spec=valid_spec();spec['contract_id']='novel_unreviewed_ability';spec['status']='verified'
        def forbidden(*args,**kwargs):raise AssertionError('Unknown contract must not execute')
        evidence=evaluate_capability(spec,catalog_factory=forbidden)
        self.assertEqual(evidence['status'],'needs_evaluation');self.assertEqual(evidence['fixture_count'],0)

    def test_missing_contract_has_persistable_unregistered_identity(self):
        spec=valid_spec();del spec['contract_id']
        evidence=evaluate_capability(spec)
        self.assertEqual(evidence['contract_id'],'unregistered')
        self.assertEqual(evidence['status'],'needs_evaluation')
        self.assertEqual(evidence['fixture_count'],0)

    def test_self_reported_trace_cannot_replace_actual_calls(self):
        with patch('ascendra.capability_agent.execute_workflow',return_value={'status':'ok','steps':[{'tool':'run_tests','result':{'status':'ok','data':{'tests_run':100,'successful':True}}}],'error':None}):
            evidence=evaluate_capability(valid_spec())
        self.assertEqual(evidence['status'],'failed')
        self.assertTrue(all(not result['passed'] for result in evidence['results']))

    def test_zero_discovery_and_boolean_counts_fail_closed(self):
        class ZeroCatalog(ToolCatalog):
            def execute(self,name,arguments):
                result=super().execute(name,arguments)
                if name=='run_tests':result['data'].update(tests_run=0,failures=0,errors=0,successful=True)
                return result
        class BooleanCatalog(ToolCatalog):
            def execute(self,name,arguments):
                result=super().execute(name,arguments)
                if name=='run_tests':result['data']['failures']=False
                return result
        self.assertEqual(evaluate_capability(valid_spec(),ZeroCatalog)['status'],'failed')
        self.assertEqual(evaluate_capability(valid_spec(),BooleanCatalog)['status'],'failed')

    def test_search_must_find_actual_source_and_read_must_return_content(self):
        class EmptySearch(ToolCatalog):
            def execute(self,name,arguments):
                result=super().execute(name,arguments)
                if name=='search_text':result['data']['matches']=[]
                return result
        class EmptyRead(ToolCatalog):
            def execute(self,name,arguments):
                result=super().execute(name,arguments)
                if name=='read_file':result['data']['content']=''
                return result
        for factory in (EmptySearch,EmptyRead):
            self.assertEqual(evaluate_capability(valid_spec(),factory)['status'],'failed')

    def test_invalid_tools_templates_and_hardcoded_paths_rejected(self):
        variants=[]
        spec=valid_spec();spec['steps'][0]['tool']='shell';variants.append(spec)
        spec=valid_spec();spec['steps'][0]['arguments']['path']='fixed.py';variants.append(spec)
        spec=valid_spec();spec['steps'][2]['arguments']['start_dir']='tests';variants.append(spec)
        spec=valid_spec();spec['steps'][0]['arguments']['path']='prefix/$input.source_path';variants.append(spec)
        spec=valid_spec();spec['steps'].append({'tool':'write_file','arguments':{'path':'x','content':'print(1)'}});variants.append(spec)
        spec=valid_spec();spec['steps'].append(copy.deepcopy(spec['steps'][2]));variants.append(spec)
        for spec in variants:
            with self.subTest(steps=spec['steps']):
                evidence=evaluate_capability(spec)
                self.assertEqual(evidence['status'],'needs_evaluation');self.assertTrue(evidence['validation_error']);self.assertEqual(evidence['fixture_count'],0)

    def test_unregistered_novel_and_invalid_proposals_persist_without_verification(self):
        import tempfile
        from ascendra.capability_memory import ExperienceStore
        variants=[]
        missing=valid_spec();del missing['contract_id'];variants.append(missing)
        novel=valid_spec();novel['contract_id']='new_unreviewed_contract';variants.append(novel)
        invalid=valid_spec();invalid['steps'][0]['arguments']['path']='hardcoded.py';variants.append(invalid)
        with tempfile.TemporaryDirectory() as directory:
            store=ExperienceStore(directory)
            for spec in variants:
                capability_id=store.propose(spec)
                saved=store.get_capability(capability_id)
                evidence=evaluate_capability(saved['spec'])
                result=store.record_evaluation(capability_id,evidence)
                self.assertEqual(evidence['status'],'needs_evaluation')
                self.assertEqual(result['status'],'needs_evaluation')
            self.assertEqual(store.list_capabilities(status='verified'),[])

    def test_nonfinite_spec_rejected(self):
        spec=valid_spec();spec['extra']=float('nan')
        evidence=evaluate_capability(spec)
        self.assertEqual(evidence['status'],'needs_evaluation')
        self.assertTrue(evidence['validation_error'])


if __name__=='__main__':unittest.main()
