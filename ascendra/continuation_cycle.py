"""Research continuation and trusted, bounded candidate evaluation.

No model-generated commands, approval, deployment or installation mutation.
The evaluator is operator-owned code, not a callback supplied by a candidate.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import shutil

from .studio_research import research
from .studio_proposals import generate_proposals


def propose_next_steps(store, topic, *, decide, urls=None, mode="self_improvement"):
    """Fetch fresh evidence and persist >=3 proposals; never create a job.

    Call once per completed run from the executor. Failed research is persisted
    but never presented as a successful recommendation. Model calls must use
    the executor's bounded decider. Restart deduplication belongs to its step ID.
    """
    evidence = research(topic, urls=urls)
    store.save_research(evidence)
    if evidence.get("status") != "complete":
        return {"status": "research_failed", "research_id": evidence["id"],
                "batch": None, "execution_started": False}
    batch = generate_proposals(evidence, mode=mode, decide=decide)
    store.save_batch(batch)
    return {"status": "awaiting_selection", "research_id": evidence["id"],
            "batch": batch, "execution_started": False}


def tree_digest(root):
    """Hash a bounded plain-file tree, refusing links and special files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Expected plain directory")
    digest = hashlib.sha256()
    size = count = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Links are not allowed in evaluation artifacts")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Special files are not allowed")
        count += 1
        size += path.stat().st_size
        if count > 10000 or size > 64 * 1024 * 1024:
            raise ValueError("Evaluation artifact exceeds bounds")
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(8, "big")); digest.update(name)
        content = path.read_bytes()
        if len(content) > 64 * 1024 * 1024:
            raise ValueError("Evaluation artifact exceeds bounds")
        digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    if not count:
        raise ValueError("Empty evaluation artifact")
    return digest.hexdigest()


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("Invalid " + name)
    return value


def evaluate_candidate(baseline, candidate, cases, *, evaluator, evaluator_id,
                       repeats=3, budget=None, min_gain=0.05, max_regression=0.0):
    """Compare isolated copies under the same case/budget, alternating order.

    evaluator(path, case, budget, repeat) returns {score: 0..1, cost: >=0,
    seconds: >=0}. It MUST independently enforce process/time/cost limits and
    isolation. Copying files is not a security sandbox. A returned over-budget
    result is rejected. No statistical significance or promotion is implied.
    """
    if not callable(evaluator) or not isinstance(evaluator_id, str) or not evaluator_id.strip():
        raise ValueError("Trusted evaluator and immutable evaluator ID required")
    if type(repeats) is not int or not 2 <= repeats <= 10:
        raise ValueError("repeats must be 2..10")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("cases must contain 1..50 cases")
    encoded = json.dumps(cases, sort_keys=True, allow_nan=False)
    if len(encoded.encode()) > 65536:
        raise ValueError("Cases exceed bounds")
    cases = json.loads(encoded)
    budget = deepcopy(budget or {"max_cost": 0, "max_seconds": 60})
    if set(budget) != {"max_cost", "max_seconds"}:
        raise ValueError("Specify max_cost and max_seconds per evaluation")
    _number(budget["max_cost"], "max_cost")
    _number(budget["max_seconds"], "max_seconds", positive=True)
    _number(min_gain, "min_gain", positive=True)
    _number(max_regression, "max_regression")
    roots = {"baseline": Path(baseline), "candidate": Path(candidate)}
    hashes = {key: tree_digest(path) for key, path in roots.items()}
    observations = []
    # A pristine copy for each invocation prevents one run contaminating another.
    for repeat in range(repeats):
        for index, case in enumerate(cases):
            for role in (("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")):
                with tempfile.TemporaryDirectory(prefix="ascendra-evaluation-") as temp:
                    snapshot = Path(temp) / "artifact"
                    shutil.copytree(roots[role], snapshot, symlinks=True)
                    if tree_digest(snapshot) != hashes[role]:
                        raise ValueError("Artifact changed before evaluation")
                    result = evaluator(snapshot, deepcopy(case), deepcopy(budget), repeat)
                    if not isinstance(result, dict):
                        raise ValueError("Invalid evaluator result")
                    score = _number(result.get("score"), "score")
                    cost = _number(result.get("cost"), "cost")
                    seconds = _number(result.get("seconds"), "seconds")
                    if score > 1 or cost > budget["max_cost"] or seconds > budget["max_seconds"]:
                        raise ValueError("Evaluator exceeded score or resource bounds")
                    if tree_digest(snapshot) != hashes[role]:
                        raise ValueError("Evaluator modified artifact; write outputs outside artifact")
                    observations.append({"role": role, "case": index, "repeat": repeat,
                                         "score": score, "cost": cost, "seconds": seconds})
    if any(tree_digest(roots[key]) != value for key, value in hashes.items()):
        raise ValueError("Source artifact changed during evaluation")
    means = {role: [sum(row["score"] for row in observations if row["role"] == role and row["case"] == i) / repeats
                    for i in range(len(cases))] for role in roots}
    gains = [b - a for a, b in zip(means["baseline"], means["candidate"])]
    gain = sum(gains) / len(gains)
    eligible = gain >= min_gain and all(value >= -max_regression for value in gains)
    report = {"status": "eligible" if eligible else "rejected", "promoted": False,
              "artifact_sha256": hashes, "evaluator_id": evaluator_id,
              "cases_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
              "repeats": repeats, "budget_per_evaluation": budget,
              "thresholds": {"min_gain": min_gain, "max_regression": max_regression},
              "mean_gain": gain, "case_gains": gains, "observations": observations,
              "requires_explicit_promotion_policy": True}
    report["report_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return report


def _verify_report(report):
    if not isinstance(report, dict):
        raise ValueError("Expected trusted evaluation report")
    payload = deepcopy(report)
    digest = payload.pop("report_sha256", None)
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if digest != expected or payload.get("status") != "eligible" or payload.get("promoted") is not False:
        raise ValueError("Invalid or ineligible report")
    return payload


def _registry_transaction(directory, update):
    """Cooperative local-owner lock plus single-file atomic pointer/history."""
    import fcntl
    import os
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Registry must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / "versions.json"
    fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if state_path.is_symlink():
            raise ValueError("Registry state must not be a symlink")
        state = json.loads(state_path.read_text()) if state_path.exists() else None
        updated = update(state)
        handle, temporary = tempfile.mkstemp(prefix=".versions-", dir=directory)
        try:
            with os.fdopen(handle, "w") as stream:
                json.dump(updated, stream, sort_keys=True, allow_nan=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, state_path)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return updated
    finally:
        os.close(fd)


def initialize_versions(directory, baseline):
    """Explicit local-owner initialization. Existing registry cannot be reset."""
    baseline = Path(baseline).resolve(strict=True)
    def update(state):
        if state is not None:
            raise ValueError("Version registry already initialized")
        digest = tree_digest(baseline)
        return {"current": digest, "versions": {digest: str(baseline)},
                "history": [{"action": "initialize", "to": digest}]}
    return _registry_transaction(directory, update)


def promote_candidate(directory, baseline, candidate, report, *, expected_current,
                      allow_promotion=False):
    """Explicit local-owner policy; caller must provide a trusted report.

    A digest is NOT authentication. Never expose this to untrusted report JSON.
    This changes a registry pointer only, not running processes or installation.
    """
    if allow_promotion is not True:
        raise PermissionError("Explicit promotion policy required")
    checked = _verify_report(report)
    baseline, candidate = Path(baseline).resolve(strict=True), Path(candidate).resolve(strict=True)
    def update(state):
        if state is None or state["current"] != expected_current:
            raise ValueError("Stale current version")
        old, new = tree_digest(baseline), tree_digest(candidate)
        if old != expected_current or checked["artifact_sha256"] != {"baseline": old, "candidate": new}:
            raise ValueError("Artifact no longer matches evaluated version")
        if old == new:
            raise ValueError("Candidate is identical to current version")
        state["versions"][new] = str(candidate)
        state["current"] = new
        state["history"].append({"action": "promote", "from": old, "to": new,
                                 "report_sha256": report["report_sha256"]})
        return state
    return _registry_transaction(directory, update)


def rollback_version(directory, target, *, expected_current, allow_rollback=False):
    """Atomically return to a previously registered hash, if bytes still match."""
    if allow_rollback is not True:
        raise PermissionError("Explicit rollback policy required")
    def update(state):
        if state is None or state["current"] != expected_current:
            raise ValueError("Stale current version")
        if target not in state["versions"] or target == expected_current:
            raise ValueError("Unknown or already current rollback target")
        if tree_digest(state["versions"][target]) != target:
            raise ValueError("Rollback artifact has changed")
        state["current"] = target
        state["history"].append({"action": "rollback", "from": expected_current, "to": target})
        return state
    return _registry_transaction(directory, update)
