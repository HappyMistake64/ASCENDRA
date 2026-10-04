"""Versioned V4 registration and fail-closed, task-level evidence gates.

This module never opens benchmark cases. Hashes supplied by the benchmark
custodian are metadata; verify_manifest authenticates configuration, not oracles.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .statistics import wilson_interval

PROTOCOL = "METHOD_RESEARCH_V4"
METHODS = ("best_of_two", "adaptive_repair")
SELECTION_RULE = "all_pass_then_weighted_fraction_then_first"
QUALITY_GATE = {"minimum_delta": 0.05, "maximum_regressions": 0,
                "sign_p_max": 0.05, "wilson_lower_exclusive": 0.5,
                "token_ratio_max": 1.20}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def manifest_hash(manifest: dict) -> str:
    return hashlib.sha256(canonical_json(manifest).encode()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_manifest(manifest: dict) -> None:
    _require(isinstance(manifest, dict), "manifest must be an object")
    canonical_json(manifest)  # Reject NaN, infinities and non-JSON configuration.
    _require(manifest.get("protocol") == PROTOCOL, "wrong protocol")
    for key in ("experiment_id", "model", "git_commit", "data_version", "checks_version"):
        _require(isinstance(manifest.get(key), str) and bool(manifest[key].strip()), f"missing {key}")
    _require(manifest.get("reasoning") == "low", "reasoning must be low")
    _require("backend_revision" in manifest and (manifest["backend_revision"] is None or
             isinstance(manifest["backend_revision"], str)), "explicit backend revision or null required")
    _require(_sha(manifest.get("worktree_diff_sha256")), "invalid worktree diff hash")
    _require(type(manifest.get("seed")) is int, "integer seed required")
    _require(type(manifest.get("pilot", False)) is bool, "pilot must be boolean")
    for key in ("prompts", "limits", "environment"):
        _require(isinstance(manifest.get(key), dict) and bool(manifest[key]), f"missing {key}")
    _require(manifest.get("selection_rule") == SELECTION_RULE, "selection rule differs from V4")
    _require(manifest.get("gates") == QUALITY_GATE, "gates differ from registered V4")
    previous = manifest.get("previous_task_ids")
    _require(isinstance(previous, list) and all(isinstance(x, str) and x for x in previous),
             "previous_task_ids must explicitly enumerate prior registrations")
    _require(len(previous) == len(set(previous)), "duplicate prior task IDs")
    tasks = manifest.get("tasks")
    _require(isinstance(tasks, dict) and set(tasks) == {"development", "confirmation"}, "invalid task phases")
    all_ids: set[str] = set()
    pilot = manifest.get("pilot", False)
    for phase, count in (("development", 12), ("confirmation", 40)):
        entries = tasks[phase]
        _require(isinstance(entries, list), "task metadata must be a list")
        _require((0 <= len(entries) <= count if pilot else len(entries) == count), f"invalid {phase} size")
        for task in entries:
            _require(isinstance(task, dict), "task metadata must be an object")
            task_id = task.get("id")
            _require(isinstance(task_id, str) and bool(task_id), "task ID required")
            _require(task_id not in all_ids, "duplicate or overlapping task IDs")
            all_ids.add(task_id)
            _require(isinstance(task.get("difficulty"), str) and bool(task["difficulty"]), "difficulty required")
            for field in ("public_sha256", "bundle_sha256", "private_sha256"):
                _require(_sha(task.get(field)), f"invalid {field}")
            if phase == "confirmation":
                _require(task_id not in previous, "previously registered confirmation task")
    _require(bool(tasks["development"]), "at least one development task required")
    # If a schedule is persisted, it must match the deterministic derivation exactly.
    if "schedule" in manifest:
        expected = {phase: _schedule(manifest, phase) for phase in tasks}
        _require(manifest["schedule"] == expected, "schedule differs from seed/task registration")


def _schedule(manifest: dict, phase: str) -> list[dict]:
    rows = [{"task_id": task["id"], "method": method, "rep": 0}
            for task in manifest["tasks"][phase] for method in METHODS]
    rows.sort(key=lambda row: hashlib.sha256(canonical_json(
        [manifest["seed"], phase, row]).encode()).hexdigest())
    return [dict(row, order=i) for i, row in enumerate(rows)]


def make_schedule(manifest: dict, phase: str) -> list[dict]:
    validate_manifest(manifest)
    _require(phase in ("development", "confirmation"), "unknown phase")
    return _schedule(manifest, phase)


def freeze_manifest(manifest: dict, path: str | Path) -> str:
    """Exclusive creation prevents replacing a registration, even with equal content."""
    validate_manifest(manifest)
    digest = manifest_hash(manifest)
    payload = canonical_json({"manifest": manifest, "sha256": digest}) + "\n"
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(payload)
    return digest


def verify_manifest(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        frozen = json.load(stream)
    _require(isinstance(frozen, dict) and set(frozen) == {"manifest", "sha256"}, "invalid frozen envelope")
    manifest = frozen["manifest"]
    _require(manifest_hash(manifest) == frozen["sha256"], "manifest integrity mismatch")
    validate_manifest(manifest)
    return manifest


def _known_tokens(value: Any) -> bool:
    return type(value) is int and value >= 0


def validate_results(manifest: dict, phase: str, results: list[dict]) -> None:
    schedule = make_schedule(manifest, phase)
    _require(isinstance(results, list), "results must be a list")
    expected = {(row["task_id"], row["method"], row["rep"]): row["order"] for row in schedule}
    seen = set()
    digest = manifest_hash(manifest)
    for row in results:
        _require(isinstance(row, dict), "result must be an object")
        key = (row.get("task_id"), row.get("method"), row.get("rep"))
        _require(type(row.get("rep")) is int and key in expected, "unregistered result")
        _require(key not in seen, "duplicate result")
        seen.add(key)
        _require(type(row.get("order")) is int and row["order"] == expected[key], "result order mismatch")
        _require(row.get("manifest_sha256") == digest, "result belongs to different manifest")
        _require(row.get("status") == "completed" and row.get("valid") is True, "invalid or incomplete result")
        _require(type(row.get("solved")) is bool, "solved must be a boolean")
        _require(row.get("total_tokens") is None or _known_tokens(row["total_tokens"]), "invalid token count")
    _require(seen == set(expected), "incomplete schedule")


def evaluate_gates(manifest: dict, phase: str, results: list[dict],
                   preparation_tokens: int | None = None) -> dict:
    """Evaluate complete registered evidence; approval is not production promotion.

    total_tokens includes all solving/repair/retry/evaluation model usage for the row;
    preparation_tokens is total shared preparation usage, split equally by arm.
    Missing usage anywhere must remain None, never zero.
    """
    report: dict = {"protocol": PROTOCOL, "quality_pass": False,
                    "token_deployment_pass": False, "eligible_for_replication": False,
                    "promotion_allowed": False, "verdict": "INVALID_OR_INCOMPLETE"}
    try:
        validate_results(manifest, phase, results)
        _require(preparation_tokens is None or _known_tokens(preparation_tokens), "invalid preparation tokens")
    except (ValueError, TypeError) as error:
        report["reason"] = str(error)
        return report
    by_key = {(r["task_id"], r["method"]): r for r in results}
    gains = losses = baseline_correct = candidate_correct = 0
    for task in manifest["tasks"][phase]:
        baseline = by_key[task["id"], METHODS[0]]["solved"]
        candidate = by_key[task["id"], METHODS[1]]["solved"]
        baseline_correct += baseline
        candidate_correct += candidate
        gains += candidate and not baseline
        losses += baseline and not candidate
    n = len(manifest["tasks"][phase])
    discordant = gains + losses
    p_value = sum(math.comb(discordant, k) for k in range(gains, discordant + 1)) / 2**discordant
    ci_low, ci_high = wilson_interval(gains, discordant)
    delta = (candidate_correct - baseline_correct) / n if n else 0.0
    quality = n > 0 and delta >= .05 and losses == 0 and p_value <= .05 and ci_low > .5
    known = preparation_tokens is not None and all(_known_tokens(r.get("total_tokens")) for r in results)
    ratio = None
    totals = None
    if known:
        totals = {method: sum(r["total_tokens"] for r in results if r["method"] == method) + preparation_tokens / 2
                  for method in METHODS}
        if totals[METHODS[0]] > 0:
            ratio = totals[METHODS[1]] / totals[METHODS[0]]
    token_pass = ratio is not None and ratio <= 1.20
    confirmation = phase == "confirmation" and not manifest.get("pilot", False) and n == 40
    report.update(total_tasks=n, baseline_correct=baseline_correct, candidate_correct=candidate_correct,
                  gains=gains, losses=losses, ties=n-discordant, delta=delta, sign_p=p_value,
                  wilson_low=ci_low, wilson_high=ci_high, token_ratio=ratio, token_totals=totals,
                  quality_pass=bool(quality and confirmation), token_deployment_pass=token_pass,
                  eligible_for_replication=bool(quality and confirmation),
                  verdict=("QUALITY_VERIFIED" if quality and confirmation else
                           "DEVELOPMENT_ONLY" if not confirmation else "NO_VERIFIED_IMPROVEMENT"))
    return report
