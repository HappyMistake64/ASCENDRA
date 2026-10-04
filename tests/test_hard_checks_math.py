"""Independent and fail-closed public math fixture checks; no model/private calls."""
import copy
import itertools
import unittest
from ascendra import hard_checks_math as checks

PUBLIC_TASKS = {'abc392_g': {'task_id': 'abc392_g', 'statement': 'For integers A, B, C ( A < B < C ), if they satisfy B-A = C-B, then (A, B, C) is called a fine triplet.\nYou are given a set of N distinct positive integers S = \\{ S_1, S_2, \\dots, S_N \\}. Find the number of fine triplets (A, B, C) with A, B, C \\in S.\n\nInput\n\nThe input is given from Standard Input in the following format:\nN\nS_1 S_2 \\dots S_N\n\nOutput\n\nPrint the number of fine triplets as an integer.\n\nConstraints\n\n\n- All input values are integers.\n- 1 \\le N \\le 10^6\n- 1 \\le S_i \\le 10^6\n- The elements of S are distinct.\n\nSample Input 1\n\n5\n8 3 1 5 2\n\nSample Output 1\n\n3\n\nHere, S = \\{8,3,1,5,2\\}.\nThe fine triplets to be counted are the following three:\n\n- (1,2,3)\n- (1,3,5)\n- (2,5,8)\n\nSample Input 2\n\n7\n300000 100000 499998 499999 200000 400000 500000\n\nSample Output 2\n\n5\n\nSample Input 3\n\n10\n13 1 16 15 12 4 7 10 2 19\n\nSample Output 3\n\n10', 'examples': [{'input': '5\n8 3 1 5 2', 'output': '3'}, {'input': '7\n300000 100000 499998 499999 200000 400000 500000', 'output': '5'}, {'input': '10\n13 1 16 15 12 4 7 10 2 19', 'output': '10'}]}, 'abc399_f': {'task_id': 'abc399_f', 'statement': 'You are given positive integers N, K, and an integer sequence of length N: A = (A_1, A_2, \\dots, A_N).\nFind \\displaystyle \\sum_{1\\leq l\\leq r\\leq N} \\Bigg(\\sum_{l\\leq i\\leq r} A_i\\Bigg)^K, modulo 998244353.\n\nInput\n\nThe input is given from Standard Input in the following format:\nN K\r\nA_1 A_2 \\dots A_N\n\nOutput\n\nPrint the answer.\n\nConstraints\n\n\n- 1\\leq N \\leq 2\\times 10^5\n- 1\\leq K \\leq 10\n- 0 \\leq A_i < 998244353\n- All input values are integers.\n\nSample Input 1\n\n3 2\r\n3 1 2\n\nSample Output 1\n\n75\r\n\nThe value is A_1^2+A_2^2+A_3^2+(A_1+A_2)^2+(A_2+A_3)^2+(A_1+A_2+A_3)^2=3^2+1^2+2^2+4^2+3^2+6^2=75.\n\nSample Input 2\n\n1 10\r\n0\n\nSample Output 2\n\n0\n\nSample Input 3\n\n10 5\r\n91 59 85 60 57 72 12 3 27 16\n\nSample Output 3\n\n428633385\r\n\nBe sure to find the sum modulo 998244353.', 'examples': [{'input': '3 2\n3 1 2', 'output': '75'}, {'input': '1 10\n0', 'output': '0'}, {'input': '10 5\n91 59 85 60 57 72 12 3 27 16', 'output': '428633385'}]}, 'arc194_b': {'task_id': 'arc194_b', 'statement': 'You are given a permutation P = (P_1, P_2, \\ldots, P_N) of (1, 2, \\ldots, N). Takahashi can repeatedly perform the following operation on P (possibly zero times):\n\n- Choose an integer i satisfying 1 \\leq i \\leq N-1. Pay a cost of i, and swap P_i and P_{i+1}.\n\nFind the minimum total cost required to sort P in ascending order.\n\nInput\n\nThe input is given from Standard Input in the following format:\nN\nP_1 P_2 \\ldots P_N\n\nOutput\n\nPrint the minimum total cost required to sort P in ascending order.\n\nConstraints\n\n\n- 2 \\leq N \\leq 2 \\times 10^5\n- (P_1, P_2, \\ldots, P_N) is a permutation of (1, 2, \\ldots, N).\n- All input values are integers.\n\nSample Input 1\n\n3\n3 2 1\n\nSample Output 1\n\n4\n\nTakahashi can sort P in ascending order as follows:\n\n- Pay a cost of 1 and swap P_1 = 3 and P_2 = 2. Now, P = (2, 3, 1).\n- Pay a cost of 2 and swap P_2 = 3 and P_3 = 1. Now, P = (2, 1, 3).\n- Pay a cost of 1 and swap P_1 = 2 and P_2 = 1. Now, P = (1, 2, 3).\n\nThe total cost for these operations is 4, which is the minimum possible.\n\nSample Input 2\n\n5\n2 4 1 3 5\n\nSample Output 2\n\n6\n\nSample Input 3\n\n2\n1 2\n\nSample Output 3\n\n0', 'examples': [{'input': '3\n3 2 1', 'output': '4'}, {'input': '5\n2 4 1 3 5', 'output': '6'}, {'input': '2\n1 2', 'output': '0'}]}, 'arc194_e': {'task_id': 'arc194_e', 'statement': 'You are given two strings S and T, each of length N and consisting of 0 and 1, as well as two positive integers X and Y. For i = 1, 2, \\ldots, N, let S_i denote the i-th character of S.\nDetermine whether it is possible to make S identical to T by repeatedly performing Operations A and B below any number of times (possibly zero) in any order:\n\n- \r\n(Operation A) Choose an integer i satisfying 1 \\leq i \\leq N-(X+Y)+1, S_{i} = S_{i+1} = \\cdots = S_{i+X-1} = 0, and S_{i+X} = S_{i+X+1} = \\cdots = S_{i+X+Y-1} = 1, then change each of S_{i}, S_{i+1}, \\ldots, S_{i+Y-1} to 1 and each of S_{i+Y}, S_{i+Y+1}, \\ldots, S_{i+Y+X-1} to 0.\n\n- \r\n(Operation B) Choose an integer i satisfying 1 \\leq i \\leq N-(X+Y)+1, S_{i} = S_{i+1} = \\cdots = S_{i+Y-1} = 1, and S_{i+Y} = S_{i+Y+1} = \\cdots = S_{i+Y+X-1} = 0, then change each of S_{i}, S_{i+1}, \\ldots, S_{i+X-1} to 0 and each of S_{i+X}, S_{i+X+1}, \\ldots, S_{i+X+Y-1} to 1.\n\nInput\n\nThe input is given from Standard Input in the following format:\nN X Y\r\nS\r\nT\n\nOutput\n\nIf it is possible to make S identical to T, print Yes; otherwise, print No.\n\nConstraints\n\n\n- 1 \\leq N \\leq 5 \\times 10^5\n- 1 \\leq X, Y \\leq N\n- S and T are strings of length N consisting of 0 and 1.\n- All input values are integers.\n\nSample Input 1\n\n9 2 1\r\n000111001\r\n011000011\n\nSample Output 1\n\nYes\r\n\nThe following procedure can transform S into T:\n\n- First, perform Operation A with i = 2. Now, S = 010011001.\n- Next, perform Operation B with i = 6. Now, S = 010010011.\n- Finally, perform Operation A with i = 3. Now, S = 011000011.\n\nThus, print Yes.\n\nSample Input 2\n\n1 1 1\r\n0\r\n1\n\nSample Output 2\n\nNo\r\n\nIt is impossible to make S identical to T. Thus, print No.', 'examples': [{'input': '9 2 1\n000111001\n011000011', 'output': 'Yes'}, {'input': '1 1 1\n0\n1', 'output': 'No'}]}}

class MathHardChecksTests(unittest.TestCase):
    def test_independent_oracles(self):
        evidence = checks.validate_oracles()
        self.assertEqual(evidence['weighted_sort_dijkstra_states'], 872)
        self.assertEqual(evidence['power_exhaustive_comparisons'], 480)

    def test_missing_middle_formula_exhaustively(self):
        for n in range(2, 30):
            for missing in range(1, n+1):
                values = [v for v in range(1, n+1) if v != missing]
                self.assertEqual(checks.interval_triplets(n, missing), checks.fine_brute(values))

    def test_sorting_vs_independent_dijkstra_all_six(self):
        for permutation, cost in checks.sort_distances(6).items():
            self.assertEqual(checks.sort_cost(permutation), cost)

    def test_bit_normal_form_exactly_matches_bfs_components(self):
        for n in range(1, 6):
            states = [''.join(bits) for bits in itertools.product('01', repeat=n)]
            for x in range(1, n+1):
                for y in range(1, n+1):
                    normal = {s: checks.bit_normal_form(s, x, y) for s in states}
                    for source in states:
                        expected = checks.bit_reachable(source, x, y)
                        actual = {s for s in states if normal[s] == normal[source]}
                        self.assertEqual(actual, expected)

    def test_large_power_formulas_small_independent_checks(self):
        for n in range(1, 20):
            alternating = [1 if i % 2 == 0 else checks.MOD-1 for i in range(n)]
            self.assertEqual(checks.power_brute(alternating, 10), ((n+1)//2)*((n+2)//2))
            impulse = [0]*n
            impulse[n//2] = checks.MOD-1
            self.assertEqual(checks.power_brute(impulse, 10), (n//2+1)*(n-n//2))

    def test_canonical_bundles_constraints_and_tampering(self):
        for task_id, task in PUBLIC_TASKS.items():
            bundle = checks.build_cases(task)
            cases = bundle['cases']
            self.assertLessEqual(len(cases), 18)
            self.assertEqual(len({c['label'] for c in cases}), len(cases))
            self.assertTrue(checks.verify_cases(task, cases))
            corrupt = copy.deepcopy(cases)
            corrupt[0]['output'] = 'incorrect'
            with self.assertRaises(ValueError):
                checks.verify_cases(task, corrupt)
            with self.assertRaises(ValueError):
                checks.verify_cases(task, cases[:-1])
            if task_id == 'abc392_g':
                case = next(c for c in cases if c['label'] == 'stress-million-missing-middle')
                values = list(map(int, case['input'].split()))
                self.assertEqual(values[0], 999999)
                self.assertNotIn(500000, values[1:])
                self.assertEqual(int(case['output']), checks.interval_triplets(1000000, 500000))

    def test_public_statement_or_examples_change_rejected(self):
        for field in ('statement', 'examples'):
            task = copy.deepcopy(PUBLIC_TASKS['abc399_f'])
            if field == 'statement':
                task[field] += ' changed'
            else:
                task[field][0]['output'] = '0'
            with self.assertRaises(ValueError):
                checks.build_cases(task)

    def test_out_of_bounds_fixtures_fail(self):
        invalid = [('abc392_g', '2\n1 1'), ('abc392_g', '1\n1000001'),
                   ('abc399_f', '1 0\n1'), ('abc399_f', '1 10\n998244353'),
                   ('arc194_b', '3\n1 1 3'), ('arc194_e', '2 3 1\n01\n01')]
        for task_id, text in invalid:
            with self.assertRaises(ValueError):
                checks._valid_input(task_id, text)

    def test_reference_witnesses_on_public_samples(self):
        import subprocess
        import sys
        for task_id, task in PUBLIC_TASKS.items():
            source = checks.reference_source(task_id)
            for example in task['examples']:
                run = subprocess.run([sys.executable, '-c', source], input=example['input'], text=True, capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.strip(), example['output'].strip())
