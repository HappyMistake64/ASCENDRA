"""Bounded orchestration for trusted host callbacks, not an execution sandbox.

Callbacks must enforce their own process/network timeouts and cancellation. Python
threads cannot kill a blocked callback. Generated programs must never be executed
in this host process. Verification and criteria are supplied independently of the
generator. This module does not publish artifacts or change approval policy.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time


@dataclass(frozen=True)
class Step:
    id: str
    depends_on: tuple = ()


@dataclass(frozen=True)
class WorkflowLimits:
    max_repairs: int = 3
    max_model_calls: int = 4
    max_seconds: float = 900

    def __post_init__(self):
        if type(self.max_repairs) is not int or not 0 <= self.max_repairs <= 20:
            raise ValueError("max_repairs must be 0..20")
        if type(self.max_model_calls) is not int or not 1 <= self.max_model_calls <= 21:
            raise ValueError("max_model_calls must be 1..21")
        if not isinstance(self.max_seconds, (int, float)) or not 0 < self.max_seconds <= 86400:
            raise ValueError("max_seconds must be in (0,86400]")


def validate_plan(steps):
    steps = tuple(steps)
    ids = [step.id for step in steps]
    if not steps or len(steps) > 200 or len(set(ids)) != len(ids):
        raise ValueError("Plan requires 1..200 unique steps")
    for step in steps:
        if not isinstance(step.id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", step.id):
            raise ValueError("Invalid step ID")
        if len(set(step.depends_on)) != len(step.depends_on) or any(x not in ids for x in step.depends_on):
            raise ValueError("Invalid dependency")
    done = set()
    while len(done) < len(steps):
        ready = {s.id for s in steps if s.id not in done and set(s.depends_on) <= done}
        if not ready:
            raise ValueError("Cyclic dependencies")
        done.update(ready)
    return steps


def _new_root(root):
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Symlink output paths are forbidden")
    root.mkdir(parents=True, exist_ok=False)
    return root


def _snapshot(path):
    if not path.is_dir() or path.is_symlink():
        raise ValueError("Missing candidate directory")
    result = {}
    total = 0
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError("Symlink candidate files are forbidden")
        if item.is_file():
            total += item.stat().st_size
            if total > 4 * 1024 * 1024 or len(result) >= 100:
                raise ValueError("Candidate size limit exceeded")
            result[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
        elif not item.is_dir():
            raise ValueError("Unsupported candidate file")
    if not result:
        raise ValueError("Empty candidate")
    return result


def _write_report(path, report):
    """Readers see either the previous complete report or the new one."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_plan(steps, root, *, execute, max_agents=4, cancelled=lambda: False):
    """Execute a validated DAG in isolated step directories.

execute(step, output_directory, dependency_paths) is trusted host code. It may
read dependencies but must only write its output directory. Dependency hashes
are checked for mutation. Failed prerequisites block all descendants. Cancellation
stops dispatch; already-running callbacks must cooperate before this returns.
"""
    steps = validate_plan(steps)
    if type(max_agents) is not int or not 1 <= max_agents <= 50:
        raise ValueError("max_agents must be 1..50")
    root = _new_root(root)
    states = {s.id: "pending" for s in steps}
    outputs, errors, running = {}, {}, {}

    def worker(step):
        dependencies = {key: outputs[key] for key in step.depends_on}
        before = {key: _snapshot(path) for key, path in dependencies.items()}
        output = root / step.id
        output.mkdir()
        execute(step, output, dependencies)
        for key, path in dependencies.items():
            if _snapshot(path) != before[key]:
                raise ValueError("Dependency output mutated")
        _snapshot(output)
        return output

    with ThreadPoolExecutor(max_workers=max_agents) as pool:
        while any(s in {"pending", "running"} for s in states.values()):
            stop = cancelled()
            for step in steps:
                if states[step.id] != "pending":
                    continue
                if stop:
                    states[step.id] = "cancelled"
                elif any(states[d] in {"failed", "blocked", "cancelled"} for d in step.depends_on):
                    states[step.id] = "blocked"
                elif len(running) < max_agents and all(states[d] == "completed" for d in step.depends_on):
                    states[step.id] = "running"
                    running[pool.submit(worker, step)] = step.id
            if running:
                completed, _ = wait(running, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in completed:
                    key = running.pop(future)
                    try:
                        outputs[key] = future.result()
                        states[key] = "cancelled" if cancelled() else "completed"
                    except Exception as exc:
                        states[key], errors[key] = "failed", type(exc).__name__
    result = {"status": "completed" if all(s == "completed" for s in states.values()) else
              "cancelled" if any(s == "cancelled" for s in states.values()) else "failed",
              "steps": states, "errors": errors,
              "outputs": {key: str(path) for key, path in outputs.items()}}
    _write_report(root / "plan-result.json", result)
    return result


def run_project_workflow(description, destination, *, generate, verify, repair=None,
                         limits=WorkflowLimits(), cancelled=lambda: False):
    """Generate/verify/repair immutable candidates; only independent checks verify.

generate(description, new_path); verify(path) -> {passed: bool, checks: [{name,
passed, ...}]}; repair(description, previous_path, verification, new_path).
Callbacks perform at most one model call per generation/repair invocation and
must enforce any token/cost budget themselves. No structural-only fallback is
treated as functional verification. The caller chooses meaningful test criteria.
"""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Description required")
    if not isinstance(limits, WorkflowLimits):
        raise ValueError("WorkflowLimits required")
    root = _new_root(destination)
    started, calls = time.monotonic(), 0
    attempts, previous, verification = [], None, None
    result = {"status": "failed", "reason": "repair_budget_exhausted", "attempts": attempts,
              "published": False, "artifact": None}

    def stopped():
        if cancelled():
            return "cancelled"
        if time.monotonic() - started >= limits.max_seconds:
            return "time_budget_exhausted"
        return None

    for index in range(limits.max_repairs + 1):
        reason = stopped()
        if reason:
            result.update(status="cancelled" if reason == "cancelled" else "failed", reason=reason)
            break
        if calls >= limits.max_model_calls:
            result["reason"] = "model_call_budget_exhausted"
            break
        if index and repair is None:
            result["reason"] = "repair_unavailable"
            break
        path = root / ("candidate-%03d" % index)
        attempt = {"candidate": str(path), "status": "generating"}
        attempts.append(attempt)
        try:
            calls += 1
            if previous is None:
                generate(description, path)
            else:
                before = _snapshot(previous)
                repair(description, previous, verification, path)
                if _snapshot(previous) != before:
                    raise ValueError("Repair mutated previous candidate")
            fingerprint = _snapshot(path)
            attempt.update(status="generated", files=fingerprint)
            reason = stopped()
            if reason:
                result.update(status="cancelled" if reason == "cancelled" else "failed", reason=reason)
                break
            verification = verify(path)
            if _snapshot(path) != fingerprint:
                raise ValueError("Verifier mutated candidate")
            if not isinstance(verification, dict) or type(verification.get("passed")) is not bool:
                raise ValueError("Invalid verification result")
            checks = verification.get("checks")
            if not isinstance(checks, list) or not checks or any(
                not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip()
                or type(c.get("passed")) is not bool for c in checks
            ):
                raise ValueError("Independent named checks required")
            if verification["passed"] != all(c["passed"] for c in checks):
                raise ValueError("Inconsistent verification result")
            # Ensure evidence is persistable before accepting success.
            json.dumps(verification, allow_nan=False)
            attempt.update(status="tested", verification=verification)
            reason = stopped()
            if reason:
                result.update(status="cancelled" if reason == "cancelled" else "failed", reason=reason)
                break
            if verification["passed"]:
                attempt["status"] = "verified"
                result.update(status="verified", reason=None, artifact=str(path))
                break
            previous = path
        except Exception as exc:
            attempt.update(status="failed", error_type=type(exc).__name__)
            result["reason"] = "callback_or_contract_failure"
            break
        finally:
            result["model_calls"] = calls
            _write_report(root / "workflow-result.json", result)
    result["model_calls"] = calls
    result["elapsed_seconds"] = time.monotonic() - started
    _write_report(root / "workflow-result.json", result)
    return result
