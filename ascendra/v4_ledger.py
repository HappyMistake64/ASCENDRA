"""Durable V4 call reservations. No provider calls or outcome retries are hidden.

The token limit is an admission limit: without a provider-enforced upper bound,
actual usage may exceed a reservation. Checksums detect corruption, not a hostile
writer able to rewrite both payload and checksum. flock requires a local POSIX FS.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time


class LedgerError(RuntimeError):
    pass


class IntegrityError(LedgerError):
    pass


class BudgetExceeded(LedgerError):
    pass


class UncertainCall(LedgerError):
    pass


class ProviderFailure(RuntimeError):
    """Non-retryable provider failure with optional observed usage."""

    def __init__(self, message, usage=None):
        super().__init__(message)
        self.usage = usage


class InfrastructureFailure(ProviderFailure):
    """Transport failure with unknown outcome; never a candidate/test failure."""


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


class FileLedger:
    DEFAULTS = dict(calls=242, tokens=3_000_000, wall_seconds=21_600,
                    phase_caps=dict(development=48, confirmation=160, preparation=24, preflight=2),
                    infra_retries=8, allow_infrastructure_retry=False,
                    default_reserved_tokens=None)

    def __init__(self, directory, configuration_hash, budgets=None):
        if not isinstance(configuration_hash, str) or not configuration_hash:
            raise ValueError('configuration_hash must be nonempty')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'ledger.json'
        self.configuration_hash = configuration_hash
        self.budgets = {**self.DEFAULTS, **(budgets or {})}
        self.budgets = json.loads(_encoded(self.budgets))
        for field in ('calls', 'tokens', 'infra_retries'):
            if type(self.budgets[field]) is not int or self.budgets[field] < 0:
                raise ValueError(f'invalid {field}')
        if not isinstance(self.budgets['wall_seconds'], (int, float)) or not math.isfinite(self.budgets['wall_seconds']) or self.budgets['wall_seconds'] <= 0:
            raise ValueError('invalid wall_seconds')
        if not isinstance(self.budgets['phase_caps'], dict) or any(type(v) is not int or v < 0 for v in self.budgets['phase_caps'].values()):
            raise ValueError('invalid phase_caps')
        with self._lock() as lock:
            if not self.path.exists():
                if lock.read():
                    raise IntegrityError('Previously initialized ledger is missing')
                self._write(dict(version=1, configuration_hash=configuration_hash,
                                 budgets=self.budgets, started_at=time.time(), entries={}))
                lock.seek(0)
                lock.write('initialized')
                lock.flush()
                os.fsync(lock.fileno())
            self._read()

    @contextmanager
    def _lock(self):
        with (self.directory / 'ledger.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lock.seek(0)
            try:
                yield lock
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self):
        try:
            envelope = json.loads(self.path.read_text())
            state = envelope['state']
            if envelope['sha256'] != _digest(state):
                raise IntegrityError('Ledger checksum mismatch')
            if state['configuration_hash'] != self.configuration_hash or state['budgets'] != self.budgets:
                raise IntegrityError('Configuration or budgets differ; use a new experiment directory')
            if state['version'] != 1 or not isinstance(state['entries'], dict):
                raise IntegrityError('Invalid ledger schema')
            return state
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise IntegrityError('Unreadable ledger') from exc

    def _write(self, state):
        payload = _encoded(dict(state=state, sha256=_digest(state)))
        fd, name = tempfile.mkstemp(prefix='.ledger-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _summary(self, state):
        attempts = [a for e in state['entries'].values() for a in e['attempts']]
        phases = {}
        for a in attempts:
            phases[a['phase']] = phases.get(a['phase'], 0) + 1
        known = [a['usage'].get('total_tokens') for a in attempts]
        costs = [a['usage'].get('cost') for a in attempts]
        return dict(calls=len(attempts), phase_calls=phases,
                    infra_retries=sum(a['infrastructure_retry'] for a in attempts),
                    known_tokens=sum(v for v in known if v is not None),
                    unknown_usage_calls=sum(v is None for v in known),
                    accounted_tokens=sum(v if v is not None else a['reserved_tokens'] for v, a in zip(known, attempts)),
                    cost=sum(costs) if all(c is not None for c in costs) else None,
                    elapsed_seconds=max(0, time.time() - state['started_at']),
                    provider_hard_token_limit_enforced=all(a['hard_token_limit_enforced'] for a in attempts))

    def summary(self):
        with self._lock():
            return self._summary(self._read())

    def execute(self, key, request, invoke):
        """Persist reservation, call invoke(request), atomically save (response, usage).

        request carries phase, reserved_tokens and optionally
        hard_token_limit_enforced. Unknown usage consumes its entire reservation.
        Reusing a key with a different request is always an error.
        """
        if not isinstance(key, str) or not key or not isinstance(request, dict):
            raise ValueError('key must be nonempty and request must be a dict')
        request = json.loads(_encoded(request))
        fingerprint = _digest(request)
        with self._lock():
            state = self._read()
            entry = state['entries'].get(key)
            retry = False
            if entry:
                if entry['request_sha256'] != fingerprint or entry['request'] != request:
                    raise IntegrityError('Request differs from existing checkpoint')
                last = entry['attempts'][-1]
                if last['status'] == 'completed':
                    return last['response'], last['usage']
                retry = (last['status'] in ('reserved', 'uncertain') and
                         self.budgets['allow_infrastructure_retry'] and len(entry['attempts']) == 1)
                if not retry:
                    raise UncertainCall('Existing unfinished/failed call; automatic outcome retry forbidden')
            phase = request.get('phase', 'development')
            if phase not in self.budgets['phase_caps']:
                raise ValueError('Unregistered phase')
            reservation = request.get('reserved_tokens', self.budgets['default_reserved_tokens'])
            if type(reservation) is not int or reservation <= 0:
                raise ValueError('A positive conservative reserved_tokens value is required')
            totals = self._summary(state)
            charged_phase = 'infrastructure' if retry else phase
            if totals['calls'] >= self.budgets['calls']:
                raise BudgetExceeded('Physical call cap exhausted')
            if retry and totals['infra_retries'] >= self.budgets['infra_retries']:
                raise BudgetExceeded('Infrastructure retry cap exhausted')
            if not retry and totals['phase_calls'].get(phase, 0) >= self.budgets['phase_caps'][phase]:
                raise BudgetExceeded('Phase call cap exhausted')
            if totals['accounted_tokens'] + reservation > self.budgets['tokens']:
                raise BudgetExceeded('Token admission budget exhausted')
            if totals['elapsed_seconds'] >= self.budgets['wall_seconds']:
                raise BudgetExceeded('Wall-time admission budget exhausted')
            if entry is None:
                entry = dict(request=request, request_sha256=fingerprint, attempts=[])
                state['entries'][key] = entry
            attempt = dict(status='reserved', phase=charged_phase, origin_phase=phase,
                           infrastructure_retry=retry, reserved_tokens=reservation,
                           hard_token_limit_enforced=request.get('hard_token_limit_enforced') is True,
                           started_at=time.time(), usage=dict(total_tokens=None, cost=None))
            entry['attempts'].append(attempt)
            self._write(state)
            try:
                response, usage = invoke(json.loads(_encoded(request)))
                usage = dict(usage or {})
                total = usage.get('total_tokens')
                if total is None and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
                    total = usage['input_tokens'] + usage['output_tokens']
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError('Invalid provider token usage')
                usage['total_tokens'] = total
                usage.setdefault('cost', None)
                cost = usage['cost']
                if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
                    raise ValueError('Invalid provider cost')
                _encoded(response)
                _encoded(usage)
            except BaseException as exc:
                observed = getattr(exc, 'usage', None)
                if isinstance(observed, dict):
                    observed = dict(observed)
                    count = observed.get('total_tokens')
                    if count is None and all(type(observed.get(k)) is int and observed[k] >= 0 for k in ('input_tokens', 'output_tokens')):
                        count = observed['input_tokens'] + observed['output_tokens']
                    observed['total_tokens'] = count if type(count) is int and count >= 0 else None
                    price = observed.get('cost')
                    observed['cost'] = price if type(price) in (int, float) and math.isfinite(price) and price >= 0 else None
                    try:
                        _encoded(observed)
                        attempt['usage'] = observed
                    except (ValueError, TypeError):
                        pass
                attempt.update(status='uncertain' if isinstance(exc, (InfrastructureFailure, KeyboardInterrupt, SystemExit)) else 'failed',
                               error_type=type(exc).__name__, finished_at=time.time())
                self._write(state)
                raise
            attempt.update(status='completed', response=response, usage=usage, finished_at=time.time())
            self._write(state)
            return response, usage
