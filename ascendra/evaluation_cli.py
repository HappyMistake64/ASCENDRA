"""Local-owner research/evaluation CLI; never execute model-selected commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid

from .continuation_cycle import evaluate_candidate, propose_next_steps
from .local_llm import LocalDecider, DEFAULT_MODEL
from .studio_store import StudioStore


def script_evaluator(executable):
    """Explicit trusted operator executable; restricted environment, NOT sandbox."""
    executable = Path(executable).expanduser().resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Evaluator must be an executable operator-owned file")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    def invoke(artifact, case, budget, repeat):
        if hashlib.sha256(executable.read_bytes()).hexdigest() != digest:
            raise ValueError("Trusted evaluator changed")
        request = json.dumps({"artifact": str(artifact), "case": case,
                              "budget": budget, "repeat": repeat}).encode()
        # This bounds file output, but does not prevent network or filesystem access.
        def limits():
            import resource
            resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with tempfile.TemporaryDirectory(prefix="ascendra-evaluator-") as work:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                started = time.monotonic()
                process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                    stdout=stdout, stderr=stderr, cwd=work, start_new_session=True,
                    env={"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": work,
                         "PYTHONDONTWRITEBYTECODE": "1"}, preexec_fn=limits)
                try:
                    process.communicate(request, timeout=budget["max_seconds"])
                    if process.returncode:
                        raise ValueError("Trusted evaluator failed")
                    stdout.seek(0)
                    result = json.loads(stdout.read(65537))
                    if not isinstance(result, dict):
                        raise ValueError("Evaluator must return a JSON object")
                    # Parent-measured elapsed time cannot be understated by callback.
                    result["seconds"] = max(result.get("seconds", 0), time.monotonic() - started)
                    return result
                finally:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait()
    return invoke, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    proposal = commands.add_parser("propose-next")
    proposal.add_argument("--data", required=True, type=Path)
    proposal.add_argument("--topic", required=True)
    proposal.add_argument("--url", action="append", default=[])
    proposal.add_argument("--model", default=DEFAULT_MODEL)
    proposal.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    proposal.add_argument("--mode", choices=["project", "self_improvement"], default="self_improvement")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--baseline", required=True, type=Path)
    evaluate.add_argument("--candidate", required=True, type=Path)
    evaluate.add_argument("--cases", required=True, type=Path, help="JSON array of operator-selected cases")
    evaluate.add_argument("--trusted-evaluator", required=True, type=Path,
                          help="Explicit operator executable; runs with your OS permissions, not sandboxed")
    evaluate.add_argument("--repeats", type=int, default=3)
    evaluate.add_argument("--max-cost", type=float, default=0)
    evaluate.add_argument("--max-seconds", type=float, default=60)
    evaluate.add_argument("--min-gain", type=float, default=.05)
    evaluate.add_argument("--max-regression", type=float, default=0)
    args = parser.parse_args(argv)
    if args.command == "propose-next":
        data = args.data.expanduser().resolve()
        store = StudioStore(data / "studio.sqlite3")
        decide = LocalDecider(data / "continuations" / uuid.uuid4().hex,
                              model=args.model, endpoint=args.ollama_url, max_calls=1)
        result = propose_next_steps(store, args.topic, decide=decide, urls=args.url or None, mode=args.mode)
    else:
        if args.cases.stat().st_size > 65536:
            raise ValueError("Case file exceeds bounds")
        evaluator, digest = script_evaluator(args.trusted_evaluator)
        result = evaluate_candidate(args.baseline, args.candidate,
            json.loads(args.cases.read_text()), evaluator=evaluator,
            evaluator_id="operator-script-sha256:" + digest, repeats=args.repeats,
            budget={"max_cost": args.max_cost, "max_seconds": args.max_seconds},
            min_gain=args.min_gain, max_regression=args.max_regression)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
