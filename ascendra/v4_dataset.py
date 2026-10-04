"""Pinned public catalogue and evaluator-only materialization for the V4 pilot.

Catalogue consumers receive an explicit public-field allowlist. Only the
materializer accesses private cases, using the existing restricted V3 decoder.
Private cases are never returned from any API in this module.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .method_research_v3 import DATA_REV, DATA_SHA, decode_private

DATASET = "livecodebench/code_generation_lite"
PILOT_IDS = (
    "abc397_b", "abc388_c", "abc388_e", "abc390_c", "abc391_d",
    "abc394_d", "abc397_c", "abc392_c", "abc395_c", "abc398_b",
    "abc398_c", "abc400_c",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _rows(root):
    raw = (Path(root) / ".ascendra/lcb-source/test6.jsonl").read_bytes()
    if _sha(raw) != DATA_SHA:
        raise ValueError("Dataset fingerprint mismatch")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    ids = [row["question_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate dataset task IDs")
    return rows


def _public(row):
    examples = json.loads(row["public_test_cases"])
    if not isinstance(examples, list) or not examples:
        raise ValueError("Invalid public examples")
    public_cases = []
    for case in examples:
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str) for k in ("input", "output")):
            raise ValueError("Invalid public example format")
        public_cases.append({k: case[k] for k in ("input", "output", "testtype") if k in case})
    return {
        "task_id": row["question_id"], "statement": row["question_content"],
        "examples": public_cases, "difficulty": row["difficulty"],
        "title": row.get("question_title", ""), "platform": row["platform"],
        "date": row.get("contest_date"),
        "source": {"dataset": DATASET, "revision": DATA_REV,
                   "file": "test6.jsonl", "sha256": DATA_SHA},
    }


def load_public_catalog(root):
    """Return public fields only; never decode or return private test data."""
    return [_public(row) for row in _rows(root)]


def previous_task_ids(root, *, exclude_study=None):
    """All IDs registered previously, including invalidated/partial studies.

    exclude_study may name the current study when re-verifying a frozen run.
    The default intentionally includes every registration, regardless of status.
    """
    result = set()

    def visit(value, key=None):
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and key in {
            "task", "task_id", "question_id", "upstream_ids", "task_ids",
            "development", "confirmation", "pilot", "holdout",
        }:
            result.add(value)

    history = Path(root) / ".ascendra"
    paths = set(history.glob("*/preregistration.json")) | set(history.glob("*/manifest.json"))
    for path in sorted(paths):
        if exclude_study is not None and path.parent.name == Path(exclude_study).name:
            continue
        registration = json.loads(path.read_text())
        visit(registration)
        # V4 uses an integrity envelope and per-phase task records. Never
        # collect arbitrary `id` fields (e.g. experiment/model IDs).
        manifest = registration.get("manifest", registration)
        tasks = manifest.get("tasks", {})
        groups = tasks.values() if isinstance(tasks, dict) else [tasks]
        for group in groups:
            if isinstance(group, list):
                for task in group:
                    if isinstance(task, dict) and isinstance(task.get("id"), str):
                        result.add(task["id"])
    return result


def _encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def materialize_selected(root, study, ids):
    """Write selected tasks for the evaluator, returning hashes/counts only.

    Paths in returned metadata are relative to the study directory. The tasks
    directory is published atomically; completed calls can be resumed only if
    the dataset, requested IDs, and all frozen file hashes still match.
    """
    root = Path(root).resolve()
    study = Path(study)
    if not study.is_absolute():
        study = root / ".ascendra" / study
    study = study.resolve()
    if not study.is_relative_to(root / ".ascendra") or study == root / ".ascendra":
        raise ValueError("Study must be a dedicated directory below .ascendra")
    ids = list(ids)
    if not ids or len(ids) != len(set(ids)) or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids):
        raise ValueError("Invalid or duplicate selected task IDs")
    rows = {r["question_id"]: r for r in _rows(root)}
    if set(ids) - rows.keys():
        raise ValueError("Selected task absent from pinned dataset")
    tasks = study / "tasks"
    manifest_path = tasks / "materialization.json"
    if tasks.exists():
        if not manifest_path.is_file():
            raise ValueError("Existing tasks have no V4 materialization manifest")
        manifest = json.loads(manifest_path.read_text())
        if manifest["dataset_sha256"] != DATA_SHA or manifest["task_ids"] != ids:
            raise ValueError("Materialized selection differs")
        for item in manifest["task_metadata"]:
            for prefix in ("public", "private"):
                relative = Path(item[prefix + "_path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Invalid frozen task path")
                if _sha((study / relative).read_bytes()) != item[prefix + "_sha256"]:
                    raise ValueError("Materialized task fingerprint mismatch")
        return manifest["task_metadata"]
    if (study / "preregistration.json").exists() or (study / "manifest.json").exists():
        raise ValueError("Cannot materialize into an already registered study")
    study.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".tasks-building-", dir=study))
    try:
        metadata = []
        for task_id in ids:
            row = rows[task_id]
            public = _public(row)
            if public["platform"] != "atcoder" or any(c.get("testtype") != "stdin" for c in public["examples"]):
                raise ValueError("Only reviewed AtCoder stdin tasks are supported")
            # Evaluator-only boundary. No private content leaves this function.
            private = decode_private(row["private_test_cases"])
            if any(not isinstance(c, dict) or c.get("testtype") != "stdin" or
                   not all(isinstance(c.get(k), str) for k in ("input", "output")) for c in private):
                raise ValueError("Unsupported private testcase format")
            task = staging / task_id
            hidden = task / ".ascendra_hidden"
            hidden.mkdir(parents=True, mode=0o700)
            public_raw, private_raw = _encode(public), _encode(private)
            (task / "public.json").write_bytes(public_raw)
            (hidden / "cases.json").write_bytes(private_raw)
            (hidden / "cases.json").chmod(0o600)
            metadata.append({
                "task": task_id, "task_id": task_id, "difficulty": public["difficulty"],
                "public_cases": len(public["examples"]), "private_cases": len(private),
                "public_path": f"tasks/{task_id}/public.json",
                "private_path": f"tasks/{task_id}/.ascendra_hidden/cases.json",
                "public_sha256": _sha(public_raw), "private_sha256": _sha(private_raw),
            })
        manifest = {"dataset_sha256": DATA_SHA, "task_ids": ids, "task_metadata": metadata}
        (staging / "materialization.json").write_bytes(_encode(manifest))
        staging.rename(tasks)
        return metadata
    finally:
        if staging.exists():
            shutil.rmtree(staging)
