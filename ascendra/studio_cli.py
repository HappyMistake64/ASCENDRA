"""Research -> evidenced choices -> explicit approval -> isolated execution.

This CLI never promotes a candidate into the running installation automatically.
"""
import argparse
import json
from pathlib import Path
import uuid

from .studio_store import StudioStore


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, required=True,
                     help='Persistent state directory outside any project')
    cli.add_argument('--provider', choices=['ollama', 'codex'], default='ollama',
                     help='Local Ollama by default; codex explicitly uses subscription access')
    cli.add_argument('--model', default=None,
                     help='Default: qwen2.5-coder:7b for Ollama; gpt-6-astra for Codex')
    cli.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    commands = cli.add_subparsers(dest='command', required=True)
    propose = commands.add_parser('propose', help='Fresh web research and at least three choices')
    propose.add_argument('topic')
    propose.add_argument('--url', action='append', default=[])
    propose.add_argument('--mode', choices=['project', 'self_improvement'], default='project')
    approve = commands.add_parser('approve')
    approve.add_argument('batch_id')
    approve.add_argument('proposal_id')
    approve.add_argument('--max-calls', type=int, default=20)
    approve.add_argument('--max-agents', type=int, default=4)
    execute = commands.add_parser('execute')
    execute.add_argument('job_id')
    execute.add_argument('--project', type=Path)
    execute.add_argument('--allow-write', action='append', default=[])
    commands.add_parser('status')
    commands.add_parser('doctor', help='Make one real structured readiness call')
    cancel = commands.add_parser('cancel', help='Cancel a queued job (not a live worker)')
    cancel.add_argument('job_id')
    return cli


def _decider(args, output, max_calls, writable_paths=()):
    if getattr(args, 'provider', 'ollama') == 'ollama':
        from .local_llm import LocalDecider, DEFAULT_MODEL
        return LocalDecider(output, model=args.model or DEFAULT_MODEL,
                            endpoint=getattr(args, 'ollama_url', 'http://127.0.0.1:11434'),
                            max_calls=max_calls)
    from .capability_cli import SubscriptionDecider
    return SubscriptionDecider(output, model=args.model or 'gpt-6-astra', max_calls=max_calls,
                               writable_paths=writable_paths)


def execute_job(args, store, *, decider_factory=_decider):
    job = store.get_job(args.job_id)
    if job['state'] != 'queued':
        raise ValueError('Only a queued, explicitly approved job can start')
    source = None
    if job['mode'] == 'self_improvement':
        if not args.project or not args.allow_write:
            raise ValueError('Self-improvement needs --project and exact --allow-write paths')
        source = args.project.resolve(strict=True)
        data = args.data.resolve()
        if data == source or source in data.parents or data in source.parents:
            raise ValueError('State and source directories must not contain one another')
        from .capability_tools import ToolCatalog
        ToolCatalog(source, writable_paths=args.allow_write)
    output = args.data / 'jobs' / job['id']
    # Atomically claim the job before invoking a model. A second runner fails.
    store.claim_job(job['id'])
    try:
        output.mkdir(parents=True, exist_ok=False)
        decide = decider_factory(args, output / 'provider', job['budget']['max_calls'],
                                 args.allow_write if source else ())
        goal = json.dumps(job['proposal'], ensure_ascii=False)
        if job['mode'] == 'project':
            from .studio_projects import build_project
            report = build_project(goal, output / 'project', decide=decide)
        else:
            from .capability_autonomy import copy_public_project
            from .capability_cli import run_episode
            from .capability_memory import ExperienceStore
            from .capability_tools import ToolCatalog
            candidate = output / 'candidate'
            copy_public_project(source, candidate)
            catalog = ToolCatalog(candidate, writable_paths=args.allow_write)
            episode = run_episode(catalog, ExperienceStore(output / 'memory'), decide,
                                  goal, output / 'episode',
                                  max_steps=min(40, job['budget']['max_calls']))
            report = {'status': 'candidate_only', 'candidate': str(candidate),
                      'episode': episode, 'promoted': False,
                      'verification': 'Independent improvement evaluation still required'}
        return store.transition(job['id'], 'completed', details=report)
    except Exception as exc:
        store.transition(job['id'], 'failed', details={'error_type': type(exc).__name__})
        raise


def main(argv=None):
    args = parser().parse_args(argv)
    args.data = args.data.expanduser().resolve()
    args.data.mkdir(parents=True, exist_ok=True)
    store = StudioStore(args.data / 'studio.sqlite3')
    if args.command == 'doctor':
        decide = _decider(args, args.data / 'preflight' / uuid.uuid4().hex, 1)
        response = decide({'instruction': 'Connectivity check only. Return ready=true.'},
                          {'type': 'object', 'properties': {'ready': {'type': 'boolean'}},
                           'required': ['ready'], 'additionalProperties': False})
        if response != {'ready': True}:
            raise ValueError('Provider readiness response was invalid')
        result = {'ready': True, 'provider': args.provider,
                  'model': decide.model if args.provider == 'ollama' else args.model or 'gpt-6-astra'}
    elif args.command == 'propose':
        from .studio_research import research
        from .studio_proposals import generate_proposals
        evidence = research(args.topic, urls=args.url or None)
        store.save_research(evidence)
        if evidence['status'] != 'complete':
            result = evidence
        else:
            decide = _decider(args, args.data / 'planning' / uuid.uuid4().hex, 1)
            result = generate_proposals(evidence, mode=args.mode, decide=decide)
            store.save_batch(result)
    elif args.command == 'approve':
        result = store.approve(args.batch_id, args.proposal_id,
                               max_calls=args.max_calls, max_agents=args.max_agents)
    elif args.command == 'execute':
        result = execute_job(args, store)
    elif args.command == 'cancel':
        if store.get_job(args.job_id)['state'] != 'queued':
            raise ValueError('CLI cancellation currently supports queued jobs only')
        result = store.transition(args.job_id, 'cancelled')
    else:
        result = {'batches': store.list_batches(), 'jobs': store.list_jobs()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
