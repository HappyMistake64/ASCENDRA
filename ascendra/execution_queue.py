"""Durable local work queue with leases and fencing, not an authentication layer.

Authenticate callers before enqueue/cancel/read; workers are trusted local processes.
``enqueue(owner_id, idempotency_key, payload)`` freezes an approved request. Reusing
its key with different content raises ValueError. ``claim(worker_id)`` returns a
job including an integer ``fence``; pass that fence and worker id to heartbeat,
checkpoint and finish. An expired lease is never renewable: claim again instead.
Checkpoints survive reclaim/restart and are immutable completed-step results.

Workers MUST check their lease before external side effects and make those effects
idempotent using job/step IDs. SQLite fencing prevents stale journal writes; it
cannot undo external calls or kill processes. Cancellation immediately revokes the
lease; the runtime must separately stop subprocesses. Completion is not evidence
that functional tests passed. Times are UTC Unix seconds, using the host clock.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .studio_store import _json, _identifier


class LeaseLost(RuntimeError):
    """Worker no longer has a live lease; stop work and discard its result."""


class ExecutionQueue:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS execution_jobs (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT, lease_until REAL,
                    checkpoints TEXT NOT NULL DEFAULT '{}', result TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(owner_id,idempotency_key));
                CREATE INDEX IF NOT EXISTS execution_jobs_claim
                    ON execution_jobs(state,lease_until,created_at);
            ''')

    @contextmanager
    def _connection(self, write=False):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            if write:
                db.execute('BEGIN IMMEDIATE')
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
    def _decode(row):
        if row is None:
            return None
        job = dict(row)
        for key in ('payload', 'checkpoints', 'result'):
            job[key] = json.loads(job[key]) if job[key] is not None else None
        return job

    @staticmethod
    def _seconds(value):
        if type(value) not in (int, float) or not 1 <= value <= 3600:
            raise ValueError('lease_seconds must be from 1 to 3600')
        return value

    def enqueue(self, owner_id, idempotency_key, payload):
        _identifier(owner_id)
        _identifier(idempotency_key)
        if type(payload) is not dict:
            raise ValueError('payload must be a JSON object')
        encoded = _json(payload)
        with self._connection(write=True) as db:
            row = db.execute('SELECT * FROM execution_jobs WHERE owner_id=? AND idempotency_key=?',
                             (owner_id, idempotency_key)).fetchone()
            if row:
                if row['payload'] != encoded:
                    raise ValueError('idempotency key already belongs to a different request')
                return self._decode(row)
            now = self.clock()
            identifier = uuid.uuid4().hex
            db.execute('''INSERT INTO execution_jobs
                (id,owner_id,idempotency_key,payload,state,created_at,updated_at)
                VALUES(?,?,?,?,'queued',?,?)''',
                (identifier, owner_id, idempotency_key, encoded, now, now))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (identifier,)).fetchone())

    def get(self, job_id, *, owner_id=None):
        _identifier(job_id)
        with self._connection() as db:
            row = db.execute('SELECT * FROM execution_jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or (owner_id is not None and row['owner_id'] != owner_id):
                raise KeyError(job_id)
            return self._decode(row)

    def list_jobs(self, *, owner_id=None):
        with self._connection() as db:
            if owner_id is None:
                rows = db.execute('SELECT * FROM execution_jobs ORDER BY created_at,id')
            else:
                rows = db.execute('SELECT * FROM execution_jobs WHERE owner_id=? ORDER BY created_at,id', (owner_id,))
            return [self._decode(row) for row in rows]

    def claim(self, worker_id, *, lease_seconds=60, owner_id=None):
        _identifier(worker_id)
        self._seconds(lease_seconds)
        with self._connection(write=True) as db:
            now = self.clock()
            query = "SELECT * FROM execution_jobs WHERE (state='queued' OR (state='running' AND lease_until<=?))"
            args = [now]
            if owner_id is not None:
                query += ' AND owner_id=?'
                args.append(_identifier(owner_id))
            row = db.execute(query + ' ORDER BY created_at,id LIMIT 1', args).fetchone()
            if row is None:
                return None
            db.execute("""UPDATE execution_jobs SET state='running',worker_id=?,
                fence=fence+1,lease_until=?,updated_at=? WHERE id=?""",
                (worker_id, now + lease_seconds, now, row['id']))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (row['id'],)).fetchone())

    def _leased(self, db, job_id, worker_id, fence):
        row = db.execute('SELECT * FROM execution_jobs WHERE id=?', (_identifier(job_id),)).fetchone()
        if (row is None or row['state'] != 'running' or row['worker_id'] != worker_id
                or type(fence) is not int or row['fence'] != fence or row['lease_until'] <= self.clock()):
            raise LeaseLost('execution lease expired, revoked or replaced')
        return row

    def heartbeat(self, job_id, worker_id, fence, *, lease_seconds=60):
        self._seconds(lease_seconds)
        with self._connection(write=True) as db:
            self._leased(db, job_id, worker_id, fence)
            now = self.clock()
            db.execute('UPDATE execution_jobs SET lease_until=?,updated_at=? WHERE id=?',
                       (now + lease_seconds, now, job_id))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (job_id,)).fetchone())

    def checkpoint(self, job_id, worker_id, fence, step_id, result):
        _identifier(step_id)
        encoded = _json(result)
        with self._connection(write=True) as db:
            row = self._leased(db, job_id, worker_id, fence)
            points = json.loads(row['checkpoints'])
            if step_id in points and _json(points[step_id]) != encoded:
                raise ValueError('completed checkpoints are immutable')
            points[step_id] = json.loads(encoded)
            db.execute('UPDATE execution_jobs SET checkpoints=?,updated_at=? WHERE id=?',
                       (_json(points), self.clock(), job_id))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (job_id,)).fetchone())

    def finish(self, job_id, worker_id, fence, *, state='completed', result=None):
        if state not in ('completed', 'failed'):
            raise ValueError('finish state must be completed or failed')
        encoded = _json(result)
        with self._connection(write=True) as db:
            self._leased(db, job_id, worker_id, fence)
            db.execute('''UPDATE execution_jobs SET state=?,result=?,worker_id=NULL,
                lease_until=NULL,updated_at=? WHERE id=?''', (state, encoded, self.clock(), job_id))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (job_id,)).fetchone())

    def cancel(self, job_id, owner_id):
        _identifier(job_id)
        _identifier(owner_id)
        with self._connection(write=True) as db:
            row = db.execute('SELECT * FROM execution_jobs WHERE id=? AND owner_id=?', (job_id, owner_id)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row['state'] in ('queued', 'running'):
                db.execute("""UPDATE execution_jobs SET state='cancelled',fence=fence+1,
                    worker_id=NULL,lease_until=NULL,updated_at=? WHERE id=?""", (self.clock(), job_id))
            return self._decode(db.execute('SELECT * FROM execution_jobs WHERE id=?', (job_id,)).fetchone())
