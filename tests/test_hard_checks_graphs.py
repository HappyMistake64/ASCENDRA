import copy
import unittest

from ascendra.hard_checks_graphs import (TASK_IDS, _alkane, _alkane_brute,
    _building, _building_brute, _large, _validate_oracles, build_cases,
    parse_input, reference_output, verify_cases)


class HardGraphTests(unittest.TestCase):
    def test_independent_small_oracles(self):
        for task_id in TASK_IDS:
            with self.subTest(task_id=task_id):
                self.assertGreaterEqual(_validate_oracles(task_id),24)

    def test_derived_truth_examples_and_wrong_assumptions(self):
        truth={
            'abc394_e':('3\n-a-\n--b\n---\n','0 1 -1\n-1 0 1\n-1 -1 0\n'),
            'abc394_g':('1 3\n8 1 8\n3\n1 1 8 1 3 8\n1 1 1 1 3 8\n1 1 3 1 1 8\n','14\n7\n5\n'),
            'abc395_e':('4 3 1000000000\n2 1\n2 3\n4 3\n','3000000003\n'),
            'abc394_f':('5\n1 2\n1 3\n1 4\n1 5\n','5\n'),
        }
        for task_id,(text,expected) in truth.items():
            self.assertEqual(reference_output(task_id,text),expected)
        self.assertEqual(reference_output('abc394_e','1\nz\n'),'0\n')
        self.assertEqual(reference_output('abc394_f','1\n'),'-1\n')
        self.assertEqual(reference_output('abc394_f','4\n1 2\n2 3\n3 4\n'),'-1\n')
        self.assertEqual(reference_output('abc395_e','2 3 1\n1 1\n2 1\n2 1\n'),'2\n')

    def test_public_examples_and_canonical_integrity(self):
        task={'task_id':'abc394_e','statement':'Public palindrome problem','examples':[{'input':'1\n-\n','output':'0\n'}]}
        bundle=build_cases(task);self.assertTrue(verify_cases(task,bundle['cases']))
        bad=copy.deepcopy(bundle['cases']);bad[0]['output']='1\n'
        with self.assertRaises(ValueError):verify_cases(task,bad)
        with self.assertRaises(ValueError):verify_cases(task,bundle['cases'][:-1])
        badtask=copy.deepcopy(task);badtask['examples'][0]['output']='1\n'
        with self.assertRaises(ValueError):build_cases(badtask)

    def test_domain_rejects_invalid_and_unreachable_cases(self):
        invalid={
            'abc394_e':['0\n','1\nA\n','2\n--\n-\n'],
            'abc394_g':['1 1\n2\n1\n1 1 1 1 1 1\n','1 1\n1\n1\n1 1 1 1 1 2\n','1 1\n1000001\n1\n1 1 1 1 1 2\n'],
            'abc395_e':['3 1 1\n1 2\n','2 1 0\n1 2\n','2 1 1\n1 3\n'],
            'abc394_f':['3\n1 2\n1 2\n','3\n1 1\n1 2\n','3\n1 2\n'],
        }
        for task_id,inputs in invalid.items():
            for text in inputs:
                with self.subTest(task_id=task_id,text=text):
                    with self.assertRaises(ValueError):parse_input(task_id,text)

    def test_maximum_structures_have_closed_form_outputs(self):
        for task_id in TASK_IDS:
            for label,text in _large(task_id):
                with self.subTest(task_id=task_id,label=label):
                    parsed=parse_input(task_id,text);out=reference_output(task_id,text)
                    self.assertLessEqual(len(out.encode()),4*1024*1024)
                    if label=='maximum-single-letter-cycle':
                        values=[list(map(int,line.split())) for line in out.splitlines()]
                        self.assertTrue(all(values[i][j]==(j-i)%100 for i in range(100) for j in range(100)))
                    elif label=='maximum-dense-bipartite':
                        values=[list(map(int,line.split())) for line in out.splitlines()]
                        self.assertTrue(all(values[i][j]==(0 if i==j else 1 if (i<50)!=(j<50) else 2) for i in range(100) for j in range(100)))
                    elif label=='maximum-alternating-chain':self.assertEqual(int(out),199999*(10**9+1))
                    elif label=='maximum-forward-chain':self.assertEqual(int(out),199999)
                    elif label=='maximum-chain':self.assertEqual(int(out),-1)
                    elif label=='maximum-star':self.assertEqual(int(out),5)
                    elif label=='large-alkane-comb':self.assertEqual(int(out),180002)
                    elif label=='maximum-grid-low-wall':self.assertEqual(out,'1999998\n2\n999999\n1\n')
                    elif label=='maximum-uniform-grid':self.assertEqual(out,'0\n999999\n999999\n')

    def test_large_uncertified_grid_reference_rejected(self):
        # Parse accepts the legal problem domain; restricted oracle fails closed.
        n=51;floors=[2]*(n*n);floors[1]=1
        from ascendra.hard_checks_graphs import _grid_input
        text=_grid_input(n,n,floors,[(1,1,2,n,n,2)])
        parse_input('abc394_g',text)
        with self.assertRaises(ValueError):reference_output('abc394_g',text)


if __name__=='__main__':unittest.main()
