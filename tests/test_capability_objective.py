import json
from pathlib import Path
import tempfile
import unittest

from ascendra.capability_objective import verify_mean, _matches


class MeanObjectiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def verify(self, source):
        (self.root/'subject.py').write_text(source)
        return verify_mean(self.root, 'subject.py')

    def test_correct_function_passes_five_host_checked_cases(self):
        result = self.verify('def mean(values):\n    if not values: raise ValueError("empty")\n    return sum(values) / len(values)\n')
        self.assertTrue(result['success'])
        self.assertEqual((result['passed'], result['failed'], result['case_count']), (5, 0, 5))
        self.assertEqual(set(result['evidence']), {'source_sha256', 'contract_sha256', 'fixture_sha256', 'results_sha256'})

    def test_floor_division_and_wrong_empty_behavior_fail(self):
        result = self.verify('def mean(values):\n    if not values: return 0\n    return sum(values) // len(values)\n')
        self.assertFalse(result['success'])
        self.assertEqual(result['passed'], 3)
        self.assertEqual(result['failed'], 2)

    def test_zero_exit_without_protocol_output_is_not_success(self):
        result = self.verify('import os\nos._exit(0)\n')
        self.assertFalse(result['success'])
        self.assertEqual(result['passed'], 0)

    def test_fake_unittest_summary_cannot_certify_goal(self):
        result = self.verify('import os\nos.write(1, b\'{"tests_run":5,"failures":0,"errors":0,"successful":true}\')\nos._exit(0)\n')
        self.assertFalse(result['success'])
        self.assertEqual(result['passed'], 0)

    def test_claimed_pass_and_boolean_return_are_rejected(self):
        for source in ('def mean(values):\n    return True\n',
                       'def mean(values):\n    return {"passed": True}\n'):
            with self.subTest(source=source):
                self.assertFalse(self.verify(source)['success'])

    def test_extreme_numeric_protocol_value_fails_closed(self):
        self.assertFalse(_matches({'kind': 'value', 'value': 10**1000}, {'kind': 'value', 'value': 2.0}))

    def test_private_or_outside_paths_fail_without_execution(self):
        for path in ('../outside.py', '.ascendra_hidden/subject.py'):
            result = verify_mean(self.root, path)
            self.assertFalse(result['success'])
            self.assertEqual(result['results'], [])


if __name__ == '__main__':
    unittest.main()
