import copy
import hashlib
import json
import unittest

from ascendra.v4_validators import (SUPPORTED_TASKS, _TRUTH, _brute, _parse,
                                   _self_check, build_bundle, oracle_output,
                                   verify_bundle)


def _rehash(bundle):
    payload={k:v for k,v in bundle.items() if k != 'bundle_sha256'}
    bundle['bundle_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


class PublicValidatorTests(unittest.TestCase):
    def test_all_twelve_independent_oracles_and_fixed_truth(self):
        self.assertEqual(len(SUPPORTED_TASKS),12)
        for task_id in SUPPORTED_TASKS:
            with self.subTest(task_id=task_id):
                self.assertEqual(_self_check(task_id),64)
                text,expected=_TRUTH[task_id]
                self.assertEqual(oracle_output(task_id,text),expected)

    def test_bundles_include_reproducible_boundaries(self):
        for task_id in SUPPORTED_TASKS:
            with self.subTest(task_id=task_id):
                bundle=build_bundle({'task_id':task_id,'statement':'Public fixture statement'})
                self.assertTrue(verify_bundle(bundle,task_id))
                self.assertGreaterEqual(len(bundle['cases']),18)
                self.assertEqual(bundle['validation_evidence']['independent_small_cases'],64)
        first=build_bundle({'task_id':'abc397_b','statement':'Public fixture statement'})
        second=build_bundle({'task_id':'abc397_b','statement':'Public fixture statement'})
        self.assertEqual(first,second)

    def test_invalid_inputs_rejected_for_every_contract(self):
        invalid={
            'abc397_b':['','x\n','i'*101,'i o'],
            'abc388_c':['2\n2 1\n','2\n0 2\n','1\n1\n'],
            'abc388_e':['2\n1 1000000001\n','2\n3\n'],
            'abc390_c':['1 1\n?\n','1 2\n#\n','1 1\nx\n'],
            'abc391_d':['1 2\n1 1\n1\n1 1\n','2 1\n1 1\n1 1\n1\n1 1\n','1 1\n1 1\n1\n0 1\n'],
            'abc394_d':['a','() []','('*200001],
            'abc397_c':['1\n1\n','2\n1 3\n'],
            'abc392_c':['2\n1 1\n1 2\n','2\n1 2\n1 3\n'],
            'abc395_c':['0\n','1\n1000001\n'],
            'abc398_b':['1 1 1 1 1 1','1 1 1 1 1 1 14'],
            'abc398_c':['1\n0\n','1\n1000000001\n'],
            'abc400_c':['0','1000000000000000001','1 2'],
        }
        for task_id,texts in invalid.items():
            for text in texts:
                with self.subTest(task_id=task_id,text=text[:40]):
                    with self.assertRaises(ValueError): oracle_output(task_id,text)

    def test_wrong_examples_tampering_and_missing_stress_fail_closed(self):
        public={'task_id':'abc397_b','statement':'Public ticket problem','examples':[{'input':'oi\n','output':'2\n'}]}
        bundle=build_bundle(public)
        with self.assertRaises(ValueError): verify_bundle(bundle,'abc394_d')
        bad=copy.deepcopy(public);bad['examples'][0]['output']='0\n'
        with self.assertRaises(ValueError):build_bundle(bad)
        bad=copy.deepcopy(bundle);bad['cases'][0]['output']='0\n'
        with self.assertRaises(ValueError):verify_bundle(bad)
        _rehash(bad)
        with self.assertRaises(ValueError):verify_bundle(bad)
        bad=copy.deepcopy(bundle);bad['cases']=[case for case in bad['cases'] if case['label']!='maximum-i'];_rehash(bad)
        with self.assertRaises(ValueError):verify_bundle(bad)
        bad=copy.deepcopy(bundle);bad['cases'][-1]['input']='io\n';bad['cases'][-1]['output']='0\n';_rehash(bad)
        with self.assertRaises(ValueError):verify_bundle(bad)

    def test_known_wrong_algorithms_are_detected_by_truth_fixtures(self):
        # These plausible defects differ from hand-derived expected results.
        self.assertNotEqual('Yes\n',oracle_output('abc394_d','([)]\n')) # counts alone
        self.assertNotEqual('Yes\n',oracle_output('abc398_b','1 1 1 1 1 1 1\n')) # same ranks
        self.assertNotEqual('4\n',oracle_output('abc388_e','4\n1 1 2 2\n')) # reuse mochi
        self.assertNotEqual('2\n',oracle_output('abc395_c','3\n1 2 1\n')) # distance vs length
        self.assertNotEqual('Yes\nYes\n',oracle_output('abc391_d','1 1\n1 2\n2\n1 1\n2 1\n')) # disappearance boundary

    def test_maximum_numerical_boundary_has_independent_identity(self):
        # All good numbers have unique forms 2*u^2 or 4*v^2, for arbitrary u,v.
        from math import isqrt
        for n in (1,2,3,4,10**18-1,10**18):
            self.assertEqual(int(oracle_output('abc400_c',str(n))),isqrt(n//2)+isqrt(n//4))

    def test_unsupported_and_missing_statement_fail_closed(self):
        for task in ({'task_id':'unknown','statement':'x'},{'task_id':'abc397_b'}):
            with self.assertRaises(ValueError):build_bundle(task)


if __name__=='__main__':unittest.main()
