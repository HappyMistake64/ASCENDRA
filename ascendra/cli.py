import argparse, hashlib, json, shlex, shutil, subprocess, time
from pathlib import Path
from .models import Strategy
from .benchmark import BenchmarkRegistry
from .store import EvidenceStore
from .sandbox import Sandbox
from .provider import DemoProvider, CommandProvider, CodexCLIProvider
from .agent import EvolutionAgent
from .evaluator import Evaluator
from .promotion import PromotionGate
from .evolution import EvolutionEngine
from .dashboard import serve
from .subscription import SubscriptionProvider, ProviderBlocked


def build(root, provider, benchmark='demo'):
    store = EvidenceStore(root / '.ascendra' / 'evidence.db')
    tasks = BenchmarkRegistry(root / 'benchmarks' / benchmark).load()
    sandbox = Sandbox(root / '.ascendra' / 'work')
    agent = EvolutionAgent(provider)
    ev = Evaluator(sandbox, agent, store)
    return store, tasks, ev


def _doctor():
    codex = shutil.which('codex')
    report = {'python': True, 'codex_cli': bool(codex), 'codex_path': codex}
    if codex:
        cp = subprocess.run([codex, '--version'], text=True, capture_output=True)
        report['codex_version'] = (cp.stdout or cp.stderr).strip()
        try:
            auth = subprocess.run([codex, 'login', 'status'], text=True, capture_output=True, timeout=15)
            report['codex_authenticated'] = auth.returncode == 0
            report['codex_auth_status'] = (auth.stdout or auth.stderr).strip()[-500:]
        except Exception as exc:
            report['codex_authenticated'] = False; report['codex_auth_status'] = f'{type(exc).__name__}: {exc}'
    print(json.dumps(report, indent=2))
    return 0 if codex and report.get('codex_authenticated') else 2


def subscription_preflight(root, model, effort):
    provider = None
    report = {'provider': 'codex_subscription', 'model': model, 'reasoning_effort': effort}
    try:
        provider = SubscriptionProvider(root=root, model=model, effort=effort)
        provider.preflight()
        report.update(status='READY', isolation='verified', calls=provider.call_records)
        return provider
    except (ProviderBlocked, RuntimeError) as exc:
        report.update(status='BLOCKED_NESTED_PROVIDER', error=str(exc),
                      calls=provider.call_records if provider else [])
        raise ProviderBlocked(str(exc)) from None
    finally:
        directory = root / '.ascendra' / 'preflight'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'subscription-{time.time_ns()}.json'
        path.write_text(json.dumps(report, indent=2))
        print(json.dumps({**report, 'evidence_path': str(path)}, indent=2), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog='ascendra')
    p.add_argument('--root', default='.')
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('demo'); r.add_argument('--generations', type=int, default=2); r.add_argument('--replicates', type=int, default=1)
    e = sub.add_parser('evolve')
    e.add_argument('--provider-cmd')
    e.add_argument('--provider', choices=['command', 'codex_cli', 'codex_subscription'], default='command')
    e.add_argument('--benchmark', default='real_v1')
    e.add_argument('--model')
    e.add_argument('--effort', choices=['low', 'medium', 'high', 'xhigh'])
    e.add_argument('--generations', type=int, default=2)
    e.add_argument('--replicates', type=int, default=3, help='paired repeated evaluations per generation')
    e.add_argument('--fresh', action='store_true', help='archive prior evidence DB before this experiment')
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--provider', choices=['codex_cli', 'codex_subscription'], default='codex_cli')
    doctor.add_argument('--model', default='gpt-6-astra')
    doctor.add_argument('--effort', default='low')
    sub.add_parser('status'); sub.add_parser('export')
    d = sub.add_parser('dashboard'); d.add_argument('--port', type=int, default=8769)
    a = p.parse_args(argv); root = Path(a.root).resolve()

    if a.cmd == 'doctor':
        if a.provider == 'codex_subscription':
            try: subscription_preflight(root, a.model, a.effort)
            except ProviderBlocked: raise SystemExit(2)
            return
        raise SystemExit(_doctor())
    if a.cmd == 'status':
        store = EvidenceStore(root / '.ascendra' / 'evidence.db'); print(json.dumps(store.latest(), indent=2)); return
    if a.cmd == 'export':
        store = EvidenceStore(root / '.ascendra' / 'evidence.db'); out = root / '.ascendra' / 'evidence.json'; out.write_text(json.dumps(store.export(), indent=2)); print(out); return
    if a.cmd == 'dashboard':
        store = EvidenceStore(root / '.ascendra' / 'evidence.db'); serve(store, port=a.port); return

    if a.cmd == 'demo':
        provider = DemoProvider(0); benchmark = 'demo'
    elif a.provider == 'codex_cli':
        provider = CodexCLIProvider(model=a.model, effort=a.effort); benchmark = a.benchmark
    elif a.provider == 'codex_subscription':
        if not a.model or not a.effort: p.error('subscription experiments require explicit --model and --effort')
        try: provider = subscription_preflight(root, a.model, a.effort)
        except ProviderBlocked: raise SystemExit(2)
        benchmark = a.benchmark
    else:
        if not a.provider_cmd: p.error('--provider-cmd is required for --provider command')
        provider = CommandProvider(shlex.split(a.provider_cmd)); benchmark = a.benchmark

    if a.cmd == 'evolve' and a.fresh:
        db=root/'.ascendra'/'evidence.db'
        if db.exists():
            archive=root/'.ascendra'/'archive';archive.mkdir(parents=True,exist_ok=True)
            db.rename(archive/f"evidence-{time.time_ns()}.db")
    store, tasks, ev = build(root, provider, benchmark)
    if isinstance(provider, SubscriptionProvider):
        provider.event_sink = store.event
        for record in provider.call_records: store.event('provider_call', record)
    configuration = {'provider': a.cmd if a.cmd == 'demo' else a.provider,
                     'benchmark': benchmark, 'research_evidence': a.cmd != 'demo',
                     'model': getattr(a, 'model', None), 'reasoning_effort': getattr(a, 'effort', None),
                     'replicates': a.replicates, 'generations': a.generations,
                     'manifest_sha256': hashlib.sha256((root/'benchmarks'/benchmark/'manifest.json').read_bytes()).hexdigest()}
    store.event('experiment_started', configuration)
    engine = EvolutionEngine(ev, PromotionGate(), provider, store, tasks)
    initial = Strategy(
        'g0-baseline', 0, None,
        'Inspect the supplied public files and task. Make the smallest evidence-based correction. Preserve existing behavior not implicated by the task. Return only necessary complete-file replacements.',
        configuration
    )
    started = time.monotonic()
    try:
        champion, summary, history = engine.run(initial, a.generations, replicates=a.replicates)
    except ProviderBlocked as exc:
        store.event('experiment_blocked', {'error': str(exc), 'duration_s': time.monotonic()-started})
        print(f'BLOCKED_NESTED_PROVIDER: {exc}', flush=True)
        raise SystemExit(2)
    store.event('experiment_completed', {'champion': champion.id, 'duration_s': time.monotonic()-started})
    print(f'Champion: {champion.id} generation={champion.generation} solved={summary.solved}/{summary.total}')
    for h in history:
        d=h['decision']; print(f"G{h['generation']} H{h['eval_group']}: {h['candidate']} -> {d.verdict} / {'PROMOTE' if d.promote else 'REJECT'} ({d.reason}; delta={d.holdout_delta:.3f}; paired={d.gains}+/{d.losses}-/{d.ties}=)")
    if a.cmd == 'demo':
        print('WARNING: demo provider is synthetic and is NOT evidence of real recursive self-improvement.')

if __name__ == '__main__': main()
