import copy
import unittest

from ascendra.project_planner import (
    execution_dag, planning_prompt, planning_schema, validate_plan_response,
)


def approach(identifier='list', direction='Use semantic list items and delegated event handlers'):
    return {'id': identifier, 'role': 'builder', 'approach': direction, 'depends_on': []}


class PlannerTests(unittest.TestCase):
    def test_model_chooses_fewer_than_capacity(self):
        response = {'approaches': [approach()]}
        result = validate_plan_response(response, 4)
        self.assertEqual(len(result), 1)
        result[0]['approach'] = 'mutated'
        self.assertNotEqual(response['approaches'][0]['approach'], 'mutated')

    def test_distinct_directions_required(self):
        for second in [approach(), approach('cards', ' USE SEMANTIC LIST ITEMS AND DELEGATED EVENT HANDLERS ')]:
            with self.assertRaises(ValueError):
                validate_plan_response({'approaches': [approach(), second]}, 2)

    def test_capacity_is_strict_and_boolean_not_integer(self):
        for capacity in [0, 51, True, 1.5]:
            with self.assertRaises(ValueError):
                planning_schema(capacity)
        with self.assertRaises(ValueError):
            validate_plan_response({'approaches': [approach(), approach('cards', 'Use a card grid with explicit state rendering')]}, 1)

    def test_no_model_permissions_or_contract_replacement(self):
        for key, value in [('contract', {}), ('max_calls', 999), ('shell', 'echo unsafe')]:
            item = approach()
            item[key] = value
            with self.assertRaises(ValueError):
                validate_plan_response({'approaches': [item]}, 1)
        item = approach()
        item['role'] = 'deployer'
        with self.assertRaises(ValueError):
            validate_plan_response({'approaches': [item]}, 1)

    def test_no_model_dependencies_or_path_ids(self):
        for identifier in ['../escape', 'foo/bar', 'x' * 41, 'x y']:
            with self.assertRaises(ValueError):
                validate_plan_response({'approaches': [approach(identifier)]}, 1)
        item = approach()
        item['depends_on'] = ['another-agent']
        with self.assertRaises(ValueError):
            validate_plan_response({'approaches': [item]}, 1)

    def test_prompt_contract_is_detached_and_digest_stable(self):
        contract = {'version': 1, 'scenarios': [{'name': 'independent checks'}]}
        original = copy.deepcopy(contract)
        first = planning_prompt('Create app', contract, 2)
        second = planning_prompt('Create app', contract, 2)
        self.assertEqual(first['acceptance_contract_sha256'], second['acceptance_contract_sha256'])
        first['acceptance_contract']['scenarios'].clear()
        self.assertEqual(contract, original)

    def test_host_dag_requires_tests_before_selection(self):
        dag = execution_dag([approach('plan'), approach('cards', 'Use an accessible card grid and explicit state rendering')])
        dependencies = {step.id: step.depends_on for step in dag}
        self.assertEqual(dependencies['build-plan'], ('plan',))
        self.assertEqual(dependencies['verify-plan'], ('build-plan',))
        self.assertEqual(dependencies['select'], ('verify-plan', 'verify-cards'))


if __name__ == '__main__':
    unittest.main()
