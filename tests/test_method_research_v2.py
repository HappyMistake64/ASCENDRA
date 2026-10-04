import unittest
from ascendra.method_research import matches
from ascendra.method_research_v2 import ELIGIBLE_IDS,splits

class UniqueOutputEligibilityTest(unittest.TestCase):
    def test_constructive_output_requires_semantics_and_is_excluded(self):
        # Public-contract fixture; no source private case is involved.
        a,b=(0,1),(1,0)
        self.assertEqual(a[0]^a[1],1);self.assertEqual(b[0]^b[1],1)
        self.assertEqual(sum(a),sum(b))
        self.assertFalse(matches('0 1','1 0'))
        self.assertNotIn('abc396_e',ELIGIBLE_IDS)
        self.assertNotIn('abc392_d',ELIGIBLE_IDS) # floating tolerance
        self.assertNotIn('arc192_b',ELIGIBLE_IDS) # case-insensitive output

    def test_selection_is_allowlisted_and_never_reuses_prior_tasks(self):
        previous={'abc397_b','abc388_c','arc195_a','abc397_g','abc396_e','abc388_e',
                  'arc192_a','abc394_d','abc397_c','abc387_c','abc392_c','abc388_d',
                  'arc193_a','abc397_d','abc399_f','abc394_e','abc394_g','arc195_c'}
        self.assertFalse(previous&ELIGIBLE_IDS)
        medium={'abc390_d','abc390_c','abc391_d','abc394_c','abc395_c','abc398_b','abc398_c','abc400_c','abc400_d','arc191_a'}
        rows=[{'question_id':t,'platform':'atcoder','difficulty':'medium' if t in medium else 'hard'} for t in ELIGIBLE_IDS|previous]
        selected=splits(rows)
        self.assertEqual(selected,splits(rows[::-1]))
        self.assertEqual(len(selected['development']),6);self.assertEqual(len(selected['confirmation']),12)
        self.assertTrue(set(sum(selected.values(),[]))<=ELIGIBLE_IDS)
        self.assertFalse(set(selected['development'])&set(selected['confirmation']))
