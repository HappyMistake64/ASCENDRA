"""Bounded durable post-run research, awaiting human selection; no autoapproval."""
import argparse
from pathlib import Path
import time
import uuid

from .execution_queue import ExecutionQueue, LeaseLost
from .studio_store import StudioStore
from .studio_research import research
from .studio_proposals import generate_proposals
from .local_llm import LocalDecider, DEFAULT_MODEL

BUDGET = {"max_calls": 1, "max_tokens": 20480, "wall_seconds": 180}


def schedule_after_run(queue, parent, topic, urls=None, *, enabled=False):
    """Trusted executor supplies actual verified parent; separate explicit budget.

    Queue must be the dedicated continuation.sqlite3 queue. Never pass a user
    supplied parent dict directly: verification belongs to the execution worker.
    """
    if enabled is not True:
        return None
    if parent.get('state') != 'completed' or (parent.get('result') or {}).get('status') != 'verified':
        raise ValueError('Only verified completed runs may schedule continuation')
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 4000:
        raise ValueError('Invalid continuation topic')
    urls = list(urls or [])
    if len(urls) > 8 or any(not isinstance(url, str) or len(url) > 2048 for url in urls):
        raise ValueError('Invalid source URLs')
    return queue.enqueue(parent['owner_id'], parent['id'] + ':research', {
        'kind': 'post_run_research', 'parent_id': parent['id'], 'topic': topic,
        'urls': urls, 'budget': BUDGET.copy(), 'mode': 'self_improvement'})


def process_one(data, *, model=DEFAULT_MODEL, owner_id=None, research_fn=research,
                decider_factory=LocalDecider):
    """Claim one research job. Interrupted reserved model calls never replay.

    Default provider enforces the one-call ledger and remaining HTTP timeout.
    Injected functions are trusted test hooks and must honor bounded contracts.
    """
    data = Path(data)
    queue = ExecutionQueue(data / 'continuation.sqlite3')
    worker = 'research_' + uuid.uuid4().hex
    job = queue.claim(worker, lease_seconds=240, owner_id=owner_id)
    if job is None:
        return None
    identity = (job['id'], worker, job['fence'])
    payload, checkpoints = job['payload'], job['checkpoints']
    started = time.monotonic()
    try:
        if payload.get('kind') != 'post_run_research' or payload.get('budget') != BUDGET:
            raise ValueError('Invalid continuation job')
        if 'result' in checkpoints:
            return queue.finish(*identity, result=checkpoints['result'])
        if 'model_reserved' in checkpoints:
            return queue.finish(*identity, state='failed', result={
                'status': 'interrupted_uncertain', 'execution_started': False,
                'reason': 'Reserved model call will not be replayed automatically'})
        store = StudioStore(data / 'studio.sqlite3')
        if 'research' in checkpoints:
            evidence = store.get_research(checkpoints['research']['id'])
        else:
            evidence = research_fn(payload['topic'], urls=payload['urls'] or None)
            store.save_research(evidence)
            queue.checkpoint(*identity, 'research', {'id': evidence['id']})
        if evidence.get('status') != 'complete':
            return queue.finish(*identity, state='failed', result={
                'status': 'research_failed', 'research_id': evidence['id'], 'execution_started': False})
        remaining = BUDGET['wall_seconds'] - (time.monotonic() - started)
        if remaining < 1:
            raise TimeoutError('Research wall budget exhausted')
        queue.checkpoint(*identity, 'model_reserved', {'calls': 1, 'tokens': 20480})
        decide = decider_factory(data / 'continuations' / job['id'] / 'provider',
            model=model, max_calls=1, timeout_s=min(remaining, 135), max_output_tokens=4096)
        batch = generate_proposals(evidence, mode=payload['mode'], decide=decide)
        if time.monotonic() - started > BUDGET['wall_seconds']:
            raise TimeoutError('Continuation wall budget exhausted')
        # Check fence immediately before durable publication into proposal store.
        queue.heartbeat(*identity, lease_seconds=60)
        store.save_batch(batch)
        result = {'status': 'awaiting_selection', 'execution_started': False,
                  'research_id': evidence['id'], 'batch': batch, 'budget': BUDGET.copy()}
        queue.checkpoint(*identity, 'result', result)
        return queue.finish(*identity, result=result)
    except LeaseLost:
        raise
    except Exception as error:
        return queue.finish(*identity, state='failed', result={
            'status': 'failed', 'error_type': type(error).__name__, 'execution_started': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--owner')
    parser.add_argument('--once', action='store_true', help='Process one bounded job (default)')
    args = parser.parse_args(argv)
    result = process_one(args.data, model=args.model, owner_id=args.owner)
    print('idle' if result is None else result['state'])
    return 0 if result is None or result['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
