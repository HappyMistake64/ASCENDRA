"""Durable approval and execution journal; completion is not verification.

The store never executes proposal content or grants additional permissions.
Callers must authenticate user approvals before invoking ``approve``.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .studio_proposals import generate_proposals


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"paused", "completed", "failed", "cancelled"},
    "paused": {"running", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid record identifier")
    return value


def _json(value):
    """Validate bounded plain JSON, rejecting lossy/coercive serialization."""
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 20:
            raise ValueError("JSON nesting or item limit exceeded")
        if item is None or type(item) in (bool, int, float):
            return
        if type(item) is str:
            if len(item) > 65536:
                raise ValueError("JSON string limit exceeded")
            return
        if type(item) is dict:
            if len(item) > 1000 or any(type(key) is not str for key in item):
                raise ValueError("JSON object must have bounded string keys")
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
            return
        if type(item) is list:
            if len(item) > 1000:
                raise ValueError("JSON array limit exceeded")
            for child in item:
                visit(child, depth + 1)
            return
        raise ValueError("only plain JSON values are supported")

    visit(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise ValueError("JSON byte limit exceeded")
    return encoded


class StudioStore:
    """SQLite-backed state. ``path`` is a database filename, not a directory."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(batch_id, proposal_id));
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def _connection(self, write=False):
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA synchronous=FULL")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, kind, data, job_id=None):
        db.execute("INSERT INTO events(job_id,kind,payload) VALUES(?,?,?)",
                   (job_id, kind, _json({"at": _now(), **data})))

    @staticmethod
    def _record(record, alias):
        if type(record) is not dict:
            raise ValueError("record must be a JSON object")
        record = json.loads(_json(record))
        identifier = record.get("id", record.get(alias))
        if identifier is None:
            identifier = uuid.uuid4().hex
        record["id"] = _identifier(identifier)
        if alias in record and record[alias] != identifier:
            raise ValueError("conflicting record identifiers")
        return record

    def _save(self, table, record, *, research_id=None):
        payload = _json(record)
        with self._connection(write=True) as db:
            if research_id is not None:
                research_row = db.execute("SELECT payload FROM research WHERE id=?", (research_id,)).fetchone()
                if not research_row:
                    raise KeyError(research_id)
                self._validate_batch(record, json.loads(research_row[0]))
            prior = db.execute(f"SELECT payload FROM {table} WHERE id=?", (record["id"],)).fetchone()
            if prior:
                if prior[0] != payload:
                    raise ValueError("stored records are immutable")
                return json.loads(prior[0])
            db.execute(f"INSERT INTO {table}(id,payload) VALUES(?,?)", (record["id"], payload))
            self._event(db, table + "_saved", {"id": record["id"]})
        return record

    def save_research(self, research):
        return self._save("research", self._record(research, "research_id"))

    def save_batch(self, batch):
        batch = self._record(batch, "batch_id")
        proposals = batch.get("proposals")
        if type(proposals) is not list or not 3 <= len(proposals) <= 50:
            raise ValueError("batch requires 3 to 50 distinct proposals")
        normalized = []
        for proposal in proposals:
            if type(proposal) is not dict or not (proposal.get("id") or proposal.get("proposal_id")):
                raise ValueError("each proposal requires an explicit identifier")
            normalized.append(self._record(proposal, "proposal_id"))
        if len({item["id"] for item in normalized}) != len(normalized):
            raise ValueError("duplicate proposal identifiers")
        batch["proposals"] = normalized
        research_id = batch.get("research_id")
        _identifier(research_id)
        return self._save("batches", batch, research_id=research_id)

    @staticmethod
    def _validate_batch(batch, research):
        # Reuse the same strict provenance/schema checks as model generation.
        # No model or network call is made by this validation-only decider.
        mode = batch.get("mode")
        if mode not in ("project", "self_improvement"):
            raise ValueError("invalid batch mode")
        envelope = {key: batch.get(key) for key in
                    ("proposals", "recommended_id", "recommendation_reason")}
        generate_proposals(research, mode=mode, decide=lambda request, schema: envelope)

    def list_batches(self):
        with self._connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM batches ORDER BY rowid")]

    def get_research(self, research_id):
        with self._connection() as db:
            row = db.execute("SELECT payload FROM research WHERE id=?", (_identifier(research_id),)).fetchone()
        if not row:
            raise KeyError(research_id)
        return json.loads(row[0])

    def approve(self, batch_id, proposal_id, *, max_calls=20, max_agents=4):
        _identifier(batch_id)
        _identifier(proposal_id)
        if type(max_calls) is not int or not 1 <= max_calls <= 1000:
            raise ValueError("max_calls must be an integer from 1 to 1000")
        if type(max_agents) is not int or not 1 <= max_agents <= 50:
            raise ValueError("max_agents must be an integer from 1 to 50")
        with self._connection(write=True) as db:
            row = db.execute("SELECT payload FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                raise KeyError(batch_id)
            batch = json.loads(row[0])
            proposal = next((item for item in batch["proposals"] if item["id"] == proposal_id), None)
            if proposal is None:
                raise KeyError(proposal_id)
            prior = db.execute("SELECT payload FROM jobs WHERE batch_id=? AND proposal_id=?",
                               (batch_id, proposal_id)).fetchone()
            if prior:
                return json.loads(prior[0])
            research_id = _identifier(batch.get("research_id"))
            research_row = db.execute("SELECT payload FROM research WHERE id=?", (research_id,)).fetchone()
            if not research_row:
                raise KeyError(research_id)
            self._validate_batch(batch, json.loads(research_row[0]))
            now = _now()
            job = {"id": uuid.uuid4().hex, "batch_id": batch_id, "proposal_id": proposal_id,
                   "proposal": proposal, "mode": batch["mode"],
                   "budget": {"max_calls": max_calls, "max_agents": max_agents},
                   "state": "queued", "created_at": now, "updated_at": now,
                   "details": {}, "verified_improvement": False}
            db.execute("INSERT INTO jobs(id,batch_id,proposal_id,payload) VALUES(?,?,?,?)",
                       (job["id"], batch_id, proposal_id, _json(job)))
            self._event(db, "approved", {"batch_id": batch_id, "proposal_id": proposal_id,
                                         "budget": job["budget"]}, job["id"])
            return job

    def list_jobs(self):
        with self._connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM jobs ORDER BY rowid")]

    def get_job(self, job_id):
        with self._connection() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (_identifier(job_id),)).fetchone()
        if not row:
            raise KeyError(job_id)
        return json.loads(row[0])

    def claim_job(self, job_id):
        """Atomically acquire a queued job; never resume or steal a running job."""
        return self._transition(job_id, "running", expected_state="queued")

    def transition(self, job_id, state, *, details=None):
        return self._transition(job_id, state, details=details)

    def _transition(self, job_id, state, *, details=None, expected_state=None):
        _identifier(job_id)
        if not isinstance(state, str) or state not in _TRANSITIONS:
            raise ValueError("unknown job state")
        if details is not None and type(details) is not dict:
            raise ValueError("details must be a JSON object")
        details_json = _json(details) if details is not None else None
        with self._connection(write=True) as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            job = json.loads(row[0])
            old = job["state"]
            if expected_state is not None and old != expected_state:
                raise ValueError(f"job must be {expected_state} to claim")
            if state == old and old in ("completed", "failed", "cancelled") and (details is None or details_json == _json(job["details"])):
                return job
            if state not in _TRANSITIONS[old]:
                raise ValueError(f"invalid transition: {old} -> {state}")
            job.update(state=state, updated_at=_now(), details=json.loads(details_json) if details_json else {})
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (_json(job), job_id))
            self._event(db, "transition", {"from": old, "to": state, "details": job["details"]}, job_id)
            return job

    def list_events(self, job_id=None):
        with self._connection() as db:
            if job_id is None:
                rows = db.execute("SELECT sequence,job_id,kind,payload FROM events ORDER BY sequence").fetchall()
            else:
                rows = db.execute("SELECT sequence,job_id,kind,payload FROM events WHERE job_id=? ORDER BY sequence",
                                  (_identifier(job_id),)).fetchall()
        return [{"sequence": row[0], "job_id": row[1], "kind": row[2], **json.loads(row[3])} for row in rows]
