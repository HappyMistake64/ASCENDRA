import base64
from decimal import Decimal
import json
import pickle
import tempfile
import unittest
import zlib
from pathlib import Path
from ascendra.method_research import (METHODS,choose_winner,controller,decode_private,evaluate,
    make_schedule,matches,pick_program,request_for,splits,statistics)


class MethodResearchTest(unittest.TestCase):
    def test_private_decoder_supports_data_only_and_rejects_globals(self):
        cases=[{'input':'1','output':'2','testtype':'stdin'}]
        self.assertEqual(decode_private(json.dumps(cases)),cases)
        encoded=base64.b64encode(zlib.compress(pickle.dumps(json.dumps(cases)))).decode()
        self.assertEqual(decode_private(encoded),cases)
        bad=base64.b64encode(zlib.compress(pickle.dumps(eval))).decode()
        with self.assertRaisesRegex(ValueError,'Non-data'): decode_private(bad)

    def test_lcb_exact_decimal_and_line_semantics(self):
        self.assertTrue(matches(' 1.0  2 \n','1 2'))
        self.assertTrue(matches('Yes\n','Yes'))
        self.assertFalse(matches('yes','Yes'))
        self.assertFalse(matches('50000000000000000','50000000000000001'))
        self.assertFalse(matches('1\n\n2','1\n2'))
        self.assertFalse(matches('1.000001','1'))
        self.assertFalse(matches('NaN','1'))

    def test_split_is_disjoint_and_ignores_input_order_and_outcomes(self):
        rows=[{'question_id':f'{d}{i}','platform':'atcoder','difficulty':d} for d in ('medium','hard') for i in range(15)]
        a=splits(rows); self.assertEqual(a,splits(rows[::-1]))
        self.assertEqual(len(a['development']),6); self.assertEqual(len(a['confirmation']),12)
        self.assertFalse(set(a['development'])&set(a['confirmation']))
        rows[0]['private_test_cases']='unreadable'
        self.assertEqual(a,splits(rows))

    def test_schedule_balances_order_and_has_exact_budget(self):
        plan=make_schedule([str(i) for i in range(12)],['best_of_two','winner'],3)
        self.assertEqual(len(plan),72)
        for rep in range(1,4):
            subset=[s for s in plan if s['replicate']==rep]
            self.assertEqual(sum(s['method']=='best_of_two' for s in subset[::2]),6)
            for a,b in zip(subset[::2],subset[1::2]): self.assertEqual(a['task'],b['task'])

    def test_controllers_use_two_calls_and_never_include_private_fields(self):
        task={'task_id':'synthetic','statement':'Echo input','examples':[{'input':'a','output':'a'}],
              'private_test_cases':'PRIVATE_SENTINEL','canonical_solution':'SECRET'}
        for method in METHODS:
            requests=[]
            def call(stage,req):
                requests.append(req); return str(stage)
            def grade(code,cases,**kwargs):
                return {'passed':int(code=='1'),'solved':code=='1','results':[]}
            code,selection=controller(task,method,call,grade)
            self.assertEqual(len(requests),2)
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(requests));self.assertNotIn('SECRET',json.dumps(requests))
            if method=='public_repair': self.assertIn('public_feedback',requests[1])
            else: self.assertNotIn('public_feedback',requests[1])
            if method=='best_of_two': self.assertEqual(requests[0],requests[1])
            self.assertEqual(code,'2' if method=='plan_then_code' else '1')
        self.assertEqual(pick_program(['a','b'],[{'passed':1},{'passed':1}]),1)

    def test_dev_selection_does_not_take_confirmation_outcomes(self):
        results=[{'method':m,'solved':False,'selected_public_passes':0} for m in METHODS]
        winner,_=choose_winner(results);self.assertEqual(winner,'public_repair')
        results[3]['solved']=True
        self.assertEqual(choose_winner(results)[0],'critical_review')

    def test_statistics_cluster_replicates_and_regressions_block(self):
        results=[]
        for task in range(6):
            for rep in range(3):
                for method in ('best_of_two','public_repair'):
                    results.append({'task':str(task),'replicate':rep,'method':method,'solved':method=='public_repair'})
        stats=statistics(results,'public_repair')
        self.assertEqual(stats['task_sign_p'],1/64)
        self.assertEqual(stats['verdict'],'VERIFIED WORKFLOW GAIN')
        only_one=[r for r in results if r['task']=='0']
        self.assertEqual(statistics(only_one,'public_repair')['task_sign_p'],.5)
        self.assertEqual(statistics(only_one,'public_repair')['verdict'],'NO VERIFIED IMPROVEMENT')
        for r in results:
            if r['task']=='0':r['solved']=not r['solved']
        self.assertEqual(statistics(results,'public_repair')['task_regressions'],1)
        self.assertEqual(statistics(results,'public_repair')['verdict'],'NO VERIFIED IMPROVEMENT')

    def test_real_sandbox_stdin_output_and_host_isolation(self):
        cases=[{'input':'3 5\n','output':'8\n'}]
        self.assertTrue(evaluate('import sys; print(sum(map(int,sys.stdin.read().split())))',cases)['solved'])
        self.assertFalse(evaluate('print(7)',cases)['solved'])
        self.assertFalse(evaluate('raise SystemExit(0)',cases)['solved'])
        code=('from pathlib import Path\n'
              "assert not Path('/workspace').exists()\n"
              "assert not Path('/run/codex-environment').exists()\n"
              "assert sorted(p.name for p in Path('/task').iterdir())==['main.py','runner.py']\n"
              'print(8)\n')
        self.assertTrue(evaluate(code,cases)['solved'])

    def test_private_feedback_never_contains_values(self):
        report=evaluate('print("actual_secret")',[{'input':'input_secret','output':'expected_secret'}])
        text=json.dumps(report)
        for value in ('actual_secret','input_secret','expected_secret'):self.assertNotIn(value,text)
        self.assertFalse(report['solved'])


if __name__=='__main__': unittest.main()
