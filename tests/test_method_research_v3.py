import inspect
import unittest
from ascendra import method_research_v2 as old,method_research_v3 as new

class TransportRestartTest(unittest.TestCase):
    def test_fresh_namespace_same_split_and_unchanged_controller(self):
        self.assertNotEqual(old.STUDY,new.STUDY)
        self.assertEqual(old.SEED,new.SEED)
        self.assertEqual(old.ELIGIBLE_IDS,new.ELIGIBLE_IDS)
        self.assertEqual(inspect.getsource(old.controller),inspect.getsource(new.controller))
        self.assertEqual(inspect.getsource(old.evaluate),inspect.getsource(new.evaluate))
        self.assertEqual(inspect.getsource(old.statistics),inspect.getsource(new.statistics))

    def test_only_transport_deadline_is_extended(self):
        self.assertIn('timeout_s=600',inspect.getsource(new.trial))
        self.assertIn('timeout_s=600',inspect.getsource(new.run))
        self.assertEqual(inspect.getsource(old.make_schedule),inspect.getsource(new.make_schedule))
        self.assertEqual(inspect.getsource(old.choose_winner),inspect.getsource(new.choose_winner))
