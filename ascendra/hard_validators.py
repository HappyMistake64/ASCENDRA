"""Admission and integrity checks for public hard-development diagnostic bundles.

This new namespace does not change frozen V4. Cases are selected before model
generation. A passing public bundle is not evidence of general correctness or
a promotion: these deliberately harder tasks remain development data.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
from importlib import import_module
import json

VERSION = 'ascendra-hard-public-validators-v1'
MAX_CASES = 18  # 18 * 8s case deadline = 144s, below the 180s suite deadline.
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MODULE_TASKS = {
    'hard_checks_math': ('abc392_g', 'abc399_f', 'arc194_b', 'arc194_e'),
    'hard_checks_graphs': ('abc394_e', 'abc394_g', 'abc395_e', 'abc394_f'),
    'hard_checks_mixed': ('abc398_g', 'abc397_g', 'abc399_e', 'abc390_e'),
}
SUPPORTED_TASKS = tuple(task for tasks in MODULE_TASKS.values() for task in tasks)
_BUNDLE_KEYS = {'version', 'task_id', 'statement_sha256', 'public_task',
                'validated', 'cases', 'validation_evidence', 'bundle_sha256'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _public_task(task):
    _require(isinstance(task, dict), 'Task must be a public dictionary')
    task_id = task.get('task_id')
    _require(task_id in SUPPORTED_TASKS, 'Unsupported hard-development task')
    statement = task.get('statement')
    _require(isinstance(statement, str) and bool(statement.strip()), 'Missing public statement')
    examples = task.get('examples', [])
    _require(isinstance(examples, list), 'Invalid public examples')
    clean = []
    for example in examples:
        _require(isinstance(example, dict) and
                 all(isinstance(example.get(k), str) for k in ('input', 'output')),
                 'Invalid public example')
        clean.append({k: example[k] for k in ('input', 'output')})
    return {'task_id': task_id, 'statement': statement, 'examples': clean}


def _module(task_id):
    for name, ids in MODULE_TASKS.items():
        if task_id in ids:
            module = import_module('.' + name, __package__)
            _require(set(module.TASK_IDS) == set(ids), 'Oracle module task registration mismatch')
            return module
    raise ValueError('Unsupported hard-development task')


def _check_case_schema(cases):
    _require(isinstance(cases, list) and 1 <= len(cases) <= MAX_CASES,
             'Diagnostic bundle must contain 1..18 cases')
    labels = set()
    for case in cases:
        _require(isinstance(case, dict) and set(case) == {'input', 'output', 'label'},
                 'Unsupported diagnostic case fields')
        _require(all(isinstance(case[k], str) for k in ('input', 'output', 'label')),
                 'Diagnostic case fields must be strings')
        _require(case['input'].strip() and case['label'] and case['label'] not in labels,
                 'Missing input or duplicate diagnostic label')
        _require(len(case['output'].encode()) <= MAX_OUTPUT_BYTES,
                 'Reference output exceeds the registered runner output limit')
        labels.add(case['label'])


@lru_cache(maxsize=24)
def _registered_payload(task_json):
    """Cache immutable serialized reference material, never caller-owned dicts."""
    task = json.loads(task_json)
    result = _module(task['task_id']).build_cases(deepcopy(task))
    _require(isinstance(result, dict) and set(result) == {'cases', 'validation_evidence'},
             'Invalid oracle builder result')
    _check_case_schema(result['cases'])
    _require(isinstance(result['validation_evidence'], dict) and result['validation_evidence'],
             'Missing independent validation evidence')
    return _canonical(result)


def build_bundle(task):
    """Build a public-only bundle, bound to the full statement and examples."""
    public = _public_task(task)
    payload = json.loads(_registered_payload(_canonical(public)))
    bundle = {'version': VERSION, 'task_id': public['task_id'],
              'statement_sha256': hashlib.sha256(public['statement'].encode()).hexdigest(),
              'public_task': public, 'validated': True, **payload}
    bundle['bundle_sha256'] = _digest(bundle)
    verify_bundle(bundle, task_id=public['task_id'])
    return bundle


def verify_bundle(bundle, task_id=None):
    """Reject altered/rehashed cases and evidence, not just checksum corruption."""
    _require(isinstance(bundle, dict) and set(bundle) == _BUNDLE_KEYS,
             'Unsupported bundle schema')
    _require(bundle['version'] == VERSION and bundle['validated'] is True,
             'Unvalidated hard-development bundle')
    public = _public_task(bundle['public_task'])
    _require(public == bundle['public_task'], 'Public snapshot contains unsupported fields')
    _require(bundle['task_id'] == public['task_id'] and
             (task_id is None or task_id == bundle['task_id']), 'Bundle task identity mismatch')
    _require(bundle['statement_sha256'] == hashlib.sha256(public['statement'].encode()).hexdigest(),
             'Bundle statement fingerprint mismatch')
    _require(bundle['bundle_sha256'] == _digest({k: v for k, v in bundle.items() if k != 'bundle_sha256'}),
             'Modified diagnostic bundle')
    _check_case_schema(bundle['cases'])
    registered = json.loads(_registered_payload(_canonical(public)))
    _require(bundle['cases'] == registered['cases'], 'Changed registered diagnostic cases')
    _require(bundle['validation_evidence'] == registered['validation_evidence'],
             'Changed registered validation evidence')
    _require(_module(public['task_id']).verify_cases(deepcopy(public), deepcopy(bundle['cases'])) is True,
             'Independent module rejected diagnostic cases')
    return True
