import copy
import itertools
import json
from pathlib import Path
import random
import unittest

from ascendra import hard_checks_mixed as checks


class HardMixedOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tasks = json.loads((Path(__file__).parent / "fixtures/hard_public_tasks.json").read_text())
        cls.tasks = {t["task_id"]:t for t in tasks if t["task_id"] in checks.TASK_IDS}

    def test_all_public_bundles_domain_valid_and_bounded(self):
        for task_id, task in self.tasks.items():
            with self.subTest(task_id=task_id):
                bundle = checks.build_cases(task)
                self.assertLessEqual(len(bundle["cases"]),18)
                for case in bundle["cases"]:
                    checks.validate_input(task_id,case["input"])
                self.assertFalse(bundle["validation_evidence"]["private_cases_accessed"])

    def test_game_proved_families_agree_with_exhaustive_legal_play(self):
        compared = 0
        for n in range(1,6):
            edges = list(itertools.combinations(range(1,n+1),2))
            for mask in range(1 << len(edges)):
                chosen = [edge for i,edge in enumerate(edges) if mask >> i & 1]
                parts = checks._bipartition(n,chosen)
                if parts is None:
                    continue
                if n%2 or len(parts)==1 or all(a==b for a,b in parts):
                    self.assertEqual(checks.game_fixed_parity(n,chosen),checks.game_exact(n,chosen))
                    compared += 1
        self.assertGreater(compared,300)
        with self.assertRaisesRegex(ValueError,"No fixed-parity"):
            checks.game_fixed_parity(4,[])

    def test_interdiction_against_independent_simple_path_oracle(self):
        rng = random.Random(987)
        for _ in range(24):
            n = rng.randint(2,5)
            edges = [(i,i+1) for i in range(1,n)]
            edges += [tuple(rng.sample(range(1,n+1),2)) for _ in range(3)]
            paths = []
            def walk(u, visited, path):
                if u == n:
                    paths.append(path); return
                for i,(a,b) in enumerate(edges):
                    if a == u and b not in visited:
                        walk(b,visited|{b},path+[i])
            walk(1,{1},[])
            for k in range(1,len(edges)+1):
                expected = max(min(sum(i in selection for i in path) for path in paths)
                               for selection in map(set,itertools.combinations(range(len(edges)),k)))
                self.assertEqual(checks.interdiction_exact(n,k,edges),expected)
        self.assertEqual(checks.interdiction_exact(2,1,[(1,2),(1,2)]),0)

    def test_parallel_stage_proof_against_exact_subsets(self):
        for widths in ([1,2,3],[2,2,2],[1,3,1]):
            edges = [(i+1,i+2) for i,width in enumerate(widths) for _ in range(width)]
            for k in range(1,len(edges)+1):
                used = 0; expected = 0
                for width in sorted(widths):
                    if used+width > k:
                        break
                    used += width; expected += 1
                self.assertEqual(checks.interdiction_exact(len(widths)+1,k,edges),expected)

    def test_replacement_cycles_feeding_branch_and_irreversible_merge(self):
        self.assertEqual(checks.replacement_exact("ab","ba"),3)
        self.assertEqual(checks.replacement_exact("abc","baa"),3)
        self.assertEqual(checks.replacement_exact("abcd","badc"),6)
        self.assertEqual(checks.replacement_exact("abc","bcd"),3)
        self.assertEqual(checks.replacement_exact("aba","abc"),-1)
        for example in self.tasks["abc399_e"]["examples"]:
            _,s,t = checks.validate_input("abc399_e",example["input"])
            self.assertEqual(checks.replacement_exact(s,t),int(example["output"]))

    def test_vitamins_independent_subset_and_budget_oracles(self):
        rng = random.Random(765)
        for _ in range(50):
            budget = rng.randint(1,25)
            foods = [(rng.randint(1,3),rng.randint(1,200000),rng.randint(1,budget))
                     for _ in range(rng.randint(1,10))]
            self.assertEqual(checks.vitamins_exact(budget,foods),checks.vitamins_dp(budget,foods))

    def test_invalid_domains_fail_closed(self):
        invalid = {
            "abc398_g":["3 3\n1 2\n2 3\n1 3\n","2 2\n1 2\n1 2\n","2 1\n2 1\n"],
            "abc397_g":["2 1 0\n1 2\n","2 1 1\n2 1\n","2 1 1\n1 1\n"],
            "abc399_e":["2\na\nbb\n","1\nA\na\n"],
            "abc390_e":["1 3\n4 1 1\n","1 3\n1 1 4\n","1 3\n1 0 1\n"],
        }
        for task_id, cases in invalid.items():
            for raw in cases:
                with self.subTest(task=task_id,raw=raw),self.assertRaises(ValueError):
                    checks.validate_input(task_id,raw)

    def test_changed_expected_answer_is_rejected(self):
        task = self.tasks["abc390_e"]
        original = checks.build_cases(task)["cases"]
        self.assertTrue(checks.verify_cases(task,original))
        changed = copy.deepcopy(original)
        changed[-1]["output"] = "-1\n"
        with self.assertRaisesRegex(ValueError,"canonical"):
            checks.verify_cases(task,changed)


if __name__ == "__main__":
    unittest.main()
