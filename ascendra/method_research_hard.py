"""Hard-development orchestration: validated public diagnostics, immutable registration and ledger.

The default command prepares a DEVELOPMENT pilot. Confirmation requires a new,
fully reviewed registration; a pilot can never promote a workflow.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from .subscription import SubscriptionProvider, ProviderBlocked
from .method_research_v3 import SCHEMA, DATA_SHA, DATA_REV
from .hard_controller import controller, BASE, REPAIR
from .v4_protocol import (PROTOCOL, SELECTION_RULE, QUALITY_GATE, freeze_manifest,
                          verify_manifest, manifest_hash, make_schedule, evaluate_gates)
from .hard_validators import build_bundle, verify_bundle
from .v4_ledger import FileLedger, ProviderFailure
from .v4_grading import validate_private_grade, evaluate_v4 as evaluate
from .v4_dataset import load_public_catalog, previous_task_ids, materialize_selected

STUDY = 'method-search-lcb-v4-hard-pilot'
PILOT_IDS = ('abc392_g', 'abc399_f', 'arc194_b', 'arc194_e',
             'abc394_e', 'abc394_g', 'abc395_e', 'abc394_f',
             'abc398_g', 'abc397_g', 'abc399_e', 'abc390_e')
BUDGETS = {'calls': 242, 'tokens': 3000000, 'wall_seconds': 21600,
           'phase_caps': {'development': 48, 'confirmation': 160,
                          'preparation': 24, 'preflight': 2},
           'infra_retries': 8, 'allow_infrastructure_retry': False,
           'default_reserved_tokens': 40000}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def freeze_json(path, obj):
    """Exclusive and atomic checked record, used for evidence outside the ledger."""
    path = Path(path)
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    envelope = json.dumps({'sha256': digest(payload), 'payload': obj},
                          sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(envelope)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def checked_json(path):
    envelope = load(path)
    if set(envelope) != {'sha256', 'payload'}:
        raise ValueError('Invalid evidence envelope')
    raw = json.dumps(envelope['payload'], sort_keys=True, ensure_ascii=False,
                     allow_nan=False).encode()
    if digest(raw) != envelope['sha256']:
        raise ValueError('Evidence integrity mismatch')
    return envelope['payload']


def where(root):
    return Path(root) / '.ascendra' / STUDY


def sources(root):
    paths = sorted((root / 'ascendra').glob('*.py')) + sorted((root / 'tests').glob('*.py'))
    paths += sorted((root / 'tests' / 'fixtures').glob('*.json'))
    paths += [root / 'METHOD_RESEARCH_HARD.md', root / 'run_method_research_hard.sh', root / 'HARD_REVIEW.json']
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in paths}


def prepare(root):
    root = Path(root).resolve()
    study = where(root)
    if (study / 'manifest.json').exists():
        return verify(root)
    if study.exists():
        raise ValueError('Unregistered partial preparation exists; preserve it and use a fresh study namespace')
    catalogue = {t['task_id']: t for t in load_public_catalog(root)}
    # Validate every public bundle before opening any private evaluator cases.
    bundles = {task_id: build_bundle(catalogue[task_id]) for task_id in PILOT_IDS}
    study.mkdir(parents=True)
    materialize_selected(root, study, list(PILOT_IDS))
    entries = []
    for task_id in PILOT_IDS:
        folder = study / 'tasks' / task_id
        (folder / 'bundle.json').write_text(json.dumps(bundles[task_id], ensure_ascii=False, sort_keys=True))
        entries.append({'id': task_id, 'difficulty': catalogue[task_id]['difficulty'],
                        'public_sha256': digest((folder / 'public.json').read_bytes()),
                        'private_sha256': digest((folder / '.ascendra_hidden' / 'cases.json').read_bytes()),
                        'bundle_sha256': bundles[task_id]['bundle_sha256'],
                        'bundle_file_sha256': digest((folder / 'bundle.json').read_bytes())})
    diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=root)
    manifest = {'protocol': PROTOCOL, 'experiment_id': STUDY, 'pilot': True,
                'model': 'gpt-6-astra', 'reasoning': 'low', 'backend_revision': None,
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                'worktree_diff_sha256': digest(diff), 'source_files': sources(root),
                'data_version': DATA_REV, 'dataset_sha256': DATA_SHA,
                'checks_version': 'hard-public-validated-v1', 'seed': 20261005,
                'prompts': {'base': BASE, 'repair': REPAIR},
                'limits': {'budgets': BUDGETS, 'provider_timeout_seconds': 600,
                           'case_cpu_seconds': 6, 'case_wall_seconds': 8,
                           'suite_wall_seconds': 180, 'memory_bytes': 536870912,
                           'output_limit_bytes': 4194304, 'workers': 1,
                           'hard_token_ceiling_enforced': False},
                'environment': {'python': sys.version, 'platform': platform.platform(),
                                'provider': 'codex_subscription', 'tool_use': 'forbidden'},
                'selection_rule': SELECTION_RULE, 'gates': QUALITY_GATE,
                'previous_task_ids': sorted(previous_task_ids(root)),
                'tasks': {'development': entries, 'confirmation': []},
                'claim_limits': ['Deliberately harder development tasks, including exposed prior failures; no holdout claim or promotion',
                                 'Public tasks may have occurred in model training',
                                 'CLI does not expose backend revision',
                                 'Token reservation is accounting, not a transport-enforced generation cap',
                                 'Monetary cost unknown; validator human time not priced',
                                 'Structured large cases and independently checked small cases do not prove full-domain correctness']}
    freeze_manifest(manifest, study / 'manifest.json')
    return verify(root)


def verify(root):
    root = Path(root).resolve()
    study = where(root)
    manifest = verify_manifest(study / 'manifest.json')
    for name, expected in manifest['source_files'].items():
        if digest((root / name).read_bytes()) != expected:
            raise ValueError('Frozen source changed: ' + name)
    for entries in manifest['tasks'].values():
        for entry in entries:
            folder = study / 'tasks' / entry['id']
            for name, field in [('public.json', 'public_sha256'),
                                ('.ascendra_hidden/cases.json', 'private_sha256'),
                                ('bundle.json', 'bundle_file_sha256')]:
                if digest((folder / name).read_bytes()) != entry[field]:
                    raise ValueError('Frozen task material changed: ' + entry['id'] + '/' + name)
            bundle = load(folder / 'bundle.json')
            verify_bundle(bundle, task_id=entry['id'])
            if bundle['bundle_sha256'] != entry['bundle_sha256']:
                raise ValueError('Bundle does not match manifest')
    return manifest


def _invoke(provider, request, schema):
    before = len(provider.call_records)
    try:
        result = provider._exec(json.dumps(request), schema)
    except Exception as exc:
        usage = provider.call_records[-1] if len(provider.call_records) > before else None
        raise ProviderFailure(str(exc), usage=usage) from exc
    record = provider.call_records[-1]
    if record.get('status') != 'completed' or record.get('tool_calls'):
        raise ProviderBlocked('Invalid provider evidence')
    return result, record


def run_trial(root, manifest, spec, ledger, provider):
    study = where(root)
    phase = 'development'
    folder = study / 'tasks' / spec['task_id']
    out = study / 'trials' / phase / f"{spec['task_id']}__{spec['method']}__r{spec['rep']}"
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'result.json').exists():
        result = checked_json(out / 'result.json')
        if result['manifest_sha256'] != manifest_hash(manifest) or any(result.get(k) != v for k, v in spec.items()):
            raise ValueError('Result configuration mismatch')
        return result
    task, bundle = load(folder / 'public.json'), load(folder / 'bundle.json')
    usages = []
    def call(stage, request):
        key = f"{phase}/{spec['task_id']}/{spec['method']}/r{spec['rep']}/{stage}"
        envelope = {'phase': phase, 'reserved_tokens': 40000,
                    'hard_token_limit_enforced': False, 'payload': request}
        response, usage = ledger.execute(key, envelope,
                                        lambda wrapper: _invoke(provider, wrapper['payload'], SCHEMA))
        if set(response) != {'content'} or not isinstance(response['content'], str):
            raise ProviderBlocked('Invalid structured candidate response')
        usages.append(usage)
        return response['content']
    # Controller replays calls through the immutable cache if interrupted before selection.
    if (out / 'selection.json').exists():
        selected = checked_json(out / 'selection.json')
        if selected.get('manifest_sha256') != manifest_hash(manifest) or selected.get('spec') != spec or selected.get('bundle_sha256') != bundle['bundle_sha256']:
            raise ValueError('Selection configuration mismatch')
        code, selection, usages = selected['code'], selected['selection'], selected['usages']
    else:
        code, selection = controller(task, spec['method'], call, bundle)
        freeze_json(out / 'selection.json', {'code': code, 'selection': selection, 'usages': usages,
                    'manifest_sha256': manifest_hash(manifest), 'spec': spec,
                    'bundle_sha256': bundle['bundle_sha256']})
    if selection['status'] != 'evaluated' or code is None:
        raise ValueError('Public diagnostics invalid; trial is unevaluated: ' + str(selection['diagnostic_error']))
    if digest(code.encode()) != selection['program_hashes'][selection['selected_index']]:
        raise ValueError('Selected program fingerprint mismatch')
    # No private data is opened until candidate selection is frozen.
    private = load(folder / '.ascendra_hidden' / 'cases.json')
    grading = validate_private_grade(evaluate(code, private, stop_first=True), len(private))
    known = all(type(u.get('total_tokens')) is int for u in usages)
    result = {**spec, 'manifest_sha256': manifest_hash(manifest), 'status': 'completed',
              'valid': True, 'solved': bool(grading['solved'] and
                 selection['public_scores'][selection['selected_index']]['solved']),
              'total_tokens': sum(u['total_tokens'] for u in usages) if known else None,
              'model_calls': len(usages), 'selected_sha256': digest(code.encode()),
              'private_evaluation': grading, 'selected_public_passes':
                 selection['public_scores'][selection['selected_index']]['passed'],
              'public_total': selection['public_scores'][selection['selected_index']]['total'],
              'repair_triggered': spec['method'] == 'adaptive_repair' and len(usages) == 2}
    freeze_json(out / 'result.json', result)
    print(json.dumps({'event': 'trial_complete', 'task': spec['task_id'], 'method': spec['method'],
                      'solved': result['solved'], 'model_calls': result['model_calls']}), flush=True)
    return result


def run(root):
    root = Path(root).resolve()
    manifest = verify(root)
    study = where(root)
    if (study / 'summary.json').exists():
        return checked_json(study / 'summary.json')
    ledger = FileLedger(study / 'ledger', manifest_hash(manifest), manifest['limits']['budgets'])
    provider = SubscriptionProvider(root=root, timeout_s=600)
    def sink(kind, record):
        with (study / 'provider-events.jsonl').open('a') as stream:
            stream.write(json.dumps({'kind': kind, **record}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    provider.event_sink = sink
    provider.verify_isolation()
    ready_schema = {'type': 'object', 'properties': {'ready': {'type': 'boolean'}},
                    'required': ['ready'], 'additionalProperties': False}
    ready, _ = ledger.execute('preflight', {'phase': 'preflight', 'reserved_tokens': 40000,
                         'payload': {'instruction': 'Connectivity check only. Return ready=true.'}},
                         lambda wrapper: _invoke(provider, wrapper['payload'], ready_schema))
    if ready != {'ready': True}:
        raise ProviderBlocked('Provider readiness response invalid')
    results = []
    for spec in make_schedule(manifest, 'development'):
        verify(root)
        results.append(run_trial(root, manifest, spec, ledger, provider))
    verify(root)
    report = {'study': STUDY, 'manifest_sha256': manifest_hash(manifest),
              'development': evaluate_gates(manifest, 'development', results, preparation_tokens=0),
              'results': results, 'resources': ledger.summary(),
              'confirmation': {'status': 'NOT_RUN', 'reason': 'No fresh validated confirmation bundles registered'},
              'limitations': manifest['claim_limits'], 'original_lineage_promoted': False}
    freeze_json(study / 'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify', 'run', 'status'])
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.action == 'status':
            result = checked_json(where(root) / 'summary.json') if (where(root) / 'summary.json').exists() else {'status': 'NOT_COMPLETED'}
        else:
            result = {'prepare': prepare, 'verify': verify, 'run': run}[args.action](root)
        if args.action in ('prepare', 'verify'):
            result = {'study': STUDY, 'manifest_sha256': manifest_hash(result),
                      'development_tasks': len(result['tasks']['development']),
                      'confirmation_tasks': len(result['tasks']['confirmation'])}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
