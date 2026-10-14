"""Model-selected full-app approaches under a host-owned execution contract.

The model chooses implementation directions, not permissions, tests, budgets or
shell commands. Each builder creates a complete independent candidate. The host
owns the plan -> builders -> independent verification -> selection dependencies;
there is no generated merge script or shared writable candidate directory.
The caller must reserve/count the planning call before invoking its model.
"""
from copy import deepcopy
import hashlib
import json
import re

from .capability_agent import _validate_schema
from .project_workflow import Step, validate_plan


def _capacity(capacity):
    if type(capacity) is not int or not 1 <= capacity <= 50:
        raise ValueError('Planner capacity must be 1..50')
    return capacity


def planning_schema(capacity):
    """Strict small schema compatible with LocalDecider structured outputs."""
    return {'type': 'object', 'additionalProperties': False,
        'properties': {'approaches': {'type': 'array', 'minItems': 1,
            'maxItems': _capacity(capacity), 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'id': {'type': 'string', 'minLength': 1, 'maxLength': 40},
                    'role': {'type': 'string', 'enum': ['builder']},
                    'approach': {'type': 'string', 'minLength': 10, 'maxLength': 1200},
                    'depends_on': {'type': 'array', 'maxItems': 0,
                                   'items': {'type': 'string'}}},
                'required': ['id', 'role', 'approach', 'depends_on']}}},
        'required': ['approaches']}


def planning_prompt(description, contract, capacity):
    _capacity(capacity)
    if not isinstance(description, str) or not description.strip() or len(description.encode()) > 8000:
        raise ValueError('Planner description must contain 1..8000 UTF-8 bytes')
    if not isinstance(contract, dict):
        raise ValueError('Immutable acceptance contract required')
    encoded = json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 128 * 1024:
        raise ValueError('Acceptance contract too large')
    return {
        'task': 'Choose implementation approaches for complete static web application candidates.',
        'description': description,
        'acceptance_contract': deepcopy(contract),
        'acceptance_contract_sha256': hashlib.sha256(encoded.encode()).hexdigest(),
        'capacity': capacity,
        'rules': (
            'Return 1 to capacity distinct approaches, choosing fewer when extra alternatives '
            'would not help. Each approach must implement the ENTIRE requested application and '
            'the SAME acceptance contract. Use only role builder, a unique ASCII identifier '
            'of letters/digits/underscore/hyphen up to 40 characters, and empty depends_on. '
            'Describe concrete distinct implementation techniques, not separate app features. '
            'Candidates have isolated directories and cannot read or modify each other. '
            'Do not change requirements, tests, permissions, model, budgets or limits. '
            'No shell commands, packages, network services or backend. The host performs '
            'independent verification and chooses only a passing candidate. The host owns '
            'dependencies: planning, parallel independent builders, tests, then selection.'),
    }


def validate_plan_response(response, capacity):
    """Return independent defensive copies; reject injected fields/dependencies."""
    _validate_schema(response, planning_schema(capacity))
    approaches = deepcopy(response['approaches'])
    ids, directions = set(), set()
    for entry in approaches:
        identifier = entry['id']
        direction = ' '.join(entry['approach'].split()).casefold()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', identifier) or identifier in ids:
            raise ValueError('Unsafe or duplicate builder ID')
        if len(direction) < 10 or direction in directions or '\x00' in entry['approach']:
            raise ValueError('Approaches must be substantive and distinct')
        ids.add(identifier)
        directions.add(direction)
    return approaches


def execution_dag(approaches):
    """Host-owned role dependencies for display/audit or trusted DAG dispatch.

This helper describes dependencies only. Runtime must implement each role and
must not interpret model prose as executable commands. IDs are prefixed so even
an approach named 'plan' cannot replace the planning or selection step.
"""
    approaches = validate_plan_response({'approaches': approaches}, len(approaches))
    steps = [Step('plan')]
    for approach in approaches:
        builder = 'build-' + approach['id']
        steps.append(Step(builder, ('plan',)))
        steps.append(Step('verify-' + approach['id'], (builder,)))
    steps.append(Step('select', tuple('verify-' + a['id'] for a in approaches)))
    return validate_plan(steps)
