"""Append-only experience/proposal memory; no model weights or automatic promotion.

Records are logically immutable inside an atomically replaced, hash-chained local
journal. Checksums detect corruption, not a hostile writer that can recompute
all hashes. Internal evaluation/outcome methods are trusted application APIs:
they MUST NOT be offered as language-model tools. Evidence establishes the
registered contract's fixture result, not a universal capability guarantee.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


class MemoryIntegrityError(ValueError):
    pass


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _copy(value):
    return json.loads(_bytes(value))


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def capability_sha256(spec):
    """Canonical fingerprint of the stored specification (including contract_id)."""
    return _hash(spec)


def _bounded(value, limit=2000):
    raw = json.dumps(value, sort_keys=True, allow_nan=False)
    return _copy(value) if len(raw) <= limit else {'summary_json_prefix': raw[:limit], 'truncated': True}


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


class ExperienceStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'experience.json'
        with self._locked() as lock:
            if not self.path.exists():
                if lock.read():
                    raise MemoryIntegrityError('Initialized experience journal is missing')
                self._write({'version': 1, 'events': []})
                lock.seek(0)
                lock.write('initialized')
                lock.flush()
                os.fsync(lock.fileno())
            self._read()

    @contextmanager
    def _locked(self):
        with (self.directory / 'experience.lock').open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            try:
                yield stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self):
        try:
            envelope = json.loads(self.path.read_text())
            state = envelope['state']
            if _hash(state) != envelope['sha256'] or state['version'] != 1:
                raise MemoryIntegrityError('Experience checksum/version mismatch')
            previous = None
            for index, event in enumerate(state['events']):
                payload = {k: v for k, v in event.items() if k != 'sha256'}
                if event['sequence'] != index or event['previous_sha256'] != previous or event['sha256'] != _hash(payload):
                    raise MemoryIntegrityError('Experience event chain mismatch')
                previous = event['sha256']
            return state
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MemoryIntegrityError('Unreadable experience journal') from exc

    def _write(self, state):
        fd, name = tempfile.mkstemp(prefix='.experience-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(_bytes({'state': state, 'sha256': _hash(state)}))
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

    def _append(self, state, kind, data):
        events = state['events']
        event = dict(sequence=len(events), kind=kind, data=_copy(data), timestamp=time.time(),
                     previous_sha256=events[-1]['sha256'] if events else None)
        event['sha256'] = _hash(event)
        events.append(event)
        self._write(state)
        return event['sha256']

    @staticmethod
    def _episodes(state):
        return {e['data']['id']: e['data']['episode'] for e in state['events'] if e['kind'] == 'episode'}

    @staticmethod
    def _capabilities(state):
        capabilities = {}
        for event in state['events']:
            data = event['data']
            if event['kind'] == 'proposal':
                capabilities[data['id']] = dict(id=data['id'], spec=_copy(data['spec']),
                    capability_sha256=data['capability_sha256'], status='proposed', evaluations=[])
            elif event['kind'] == 'evaluation':
                capability = capabilities[data['id']]
                capability['evaluations'].append(_copy(data['evidence']))
                capability['status'] = data['status']
        return capabilities

    def record_episode(self, episode):
        episode = _copy(episode)
        if not isinstance(episode, dict):
            raise ValueError('Episode must be an object')
        outcome = episode.get('objective_success')
        if outcome is not None and type(outcome) is not bool:
            raise ValueError('objective_success must be boolean or unknown')
        observations = episode.get('tool_observations', [])
        if not isinstance(observations, list):
            raise ValueError('tool_observations must be a list')
        for observation in observations:
            if not isinstance(observation, dict) or not _nonempty(observation.get('tool')) or type(observation.get('execution_success')) is not bool:
                raise ValueError('Tool observations need tool and explicit execution_success')
            if observation.get('objective_success') is not None and type(observation['objective_success']) is not bool:
                raise ValueError('Tool objective_success must be boolean or unknown')
        with self._locked():
            state = self._read()
            episode_id = 'episode_' + _hash({'sequence': len(state['events']), 'episode': episode})[:24]
            self._append(state, 'episode', {'id': episode_id, 'episode': episode})
            return episode_id

    def record_objective_outcome(self, episode_id, success, evidence):
        """Trusted evaluator only: append measured objective outcome, never edit episode."""
        if type(success) is not bool or not isinstance(evidence, dict) or not evidence:
            raise ValueError('Objective outcome needs boolean success and nonempty evidence')
        evidence = _copy(evidence)
        with self._locked():
            state = self._read()
            if episode_id not in self._episodes(state):
                raise KeyError(episode_id)
            existing = [e['data'] for e in state['events'] if e['kind'] == 'objective_outcome' and e['data']['episode_id'] == episode_id]
            data = dict(episode_id=episode_id, success=success, evidence=evidence)
            if existing:
                if existing[-1] == data:
                    return _copy(data)
                raise ValueError('Objective already resolved; immutable outcome cannot be overwritten')
            self._append(state, 'objective_outcome', data)
            return _copy(data)

    def propose(self, spec):
        if not isinstance(spec, dict):
            raise ValueError('Capability spec must be an object')
        spec = _copy(spec)
        if 'verified' in spec or 'verification' in spec or 'evaluations' in spec:
            raise ValueError('A proposal cannot assert verification')
        spec.pop('status', None)
        required = {'name', 'description', 'motivation', 'steps', 'success_criteria'}
        if not required <= set(spec):
            raise ValueError('Missing capability specification fields')
        for field in ('name', 'description', 'motivation'):
            if not _nonempty(spec[field]):
                raise ValueError('Capability text fields must be nonempty')
        criteria = spec['success_criteria']
        if not (_nonempty(criteria) or (isinstance(criteria, list) and criteria and all(_nonempty(c) for c in criteria))):
            raise ValueError('Explicit success criteria required')
        if not isinstance(spec['steps'], list) or not 1 <= len(spec['steps']) <= 32:
            raise ValueError('Workflow needs steps')
        for step in spec['steps']:
            if not isinstance(step, dict) or not _nonempty(step.get('tool')) or not isinstance(step.get('arguments'), dict):
                raise ValueError('Each step needs a tool and argument object')
        if 'input_schema' in spec and not isinstance(spec['input_schema'], dict):
            raise ValueError('input_schema must be an object')
        capability_hash = _hash(spec)
        capability_id = 'capability_' + capability_hash[:24]
        with self._locked():
            state = self._read()
            if capability_id not in self._capabilities(state):
                self._append(state, 'proposal', dict(id=capability_id, spec=spec, capability_sha256=capability_hash))
            return capability_id

    def get_capability(self, capability_id):
        with self._locked():
            return _copy(self._capabilities(self._read())[capability_id])

    def list_capabilities(self, status=None):
        with self._locked():
            return [_copy(c) for c in self._capabilities(self._read()).values() if status is None or c['status'] == status]

    def record_evaluation(self, capability_id, evidence):
        """Trusted internal evaluator API; all fixture results and spec hash required."""
        if not isinstance(evidence, dict):
            raise ValueError('Evaluation evidence must be an object')
        evidence = _copy(evidence)
        with self._locked():
            state = self._read()
            capability = self._capabilities(state)[capability_id]
            if evidence.get('capability_sha256') != capability['capability_sha256']:
                raise ValueError('Evaluation does not bind this capability specification')
            if not _nonempty(evidence.get('contract_id')) or not _nonempty(evidence.get('verifier_version')):
                raise ValueError('Evaluation contract and verifier identity required')
            fixtures, results = evidence.get('fixtures'), evidence.get('results')
            if not isinstance(fixtures, list) or not isinstance(results, list):
                raise ValueError('Fixture definitions and results required')
            status = evidence.get('status')
            if status not in ('verified', 'failed', 'needs_evaluation'):
                raise ValueError('Unknown evaluation status')
            if type(evidence.get('fixture_count')) is not int or evidence['fixture_count'] != len(fixtures):
                raise ValueError('Incorrect declared fixture count')
            fixture_ids = []
            for fixture in fixtures:
                if not isinstance(fixture, dict) or not _nonempty(fixture.get('id')) or not _sha(fixture.get('input_sha256')) or not _sha(fixture.get('expected_sha256')):
                    raise ValueError('Invalid fixture identity/hashes')
                fixture_ids.append(fixture['id'])
            result_ids = []
            for result in results:
                if not isinstance(result, dict) or not _nonempty(result.get('fixture_id')) or type(result.get('passed')) is not bool or not _sha(result.get('actual_sha256')):
                    raise ValueError('Invalid fixture result/hashes')
                result_ids.append(result['fixture_id'])
            if len(set(fixture_ids)) != len(fixture_ids) or len(set(result_ids)) != len(result_ids) or not set(result_ids) <= set(fixture_ids):
                raise ValueError('Duplicate or unknown fixture result')
            complete = bool(fixtures) and set(fixture_ids) == set(result_ids)
            all_passed = complete and all(r['passed'] for r in results)
            if status == 'verified' and capability['spec'].get('contract_id', evidence['contract_id']) != evidence['contract_id']:
                raise ValueError('Verified evidence uses a different proposed contract')
            if status == 'verified' and not all_passed:
                raise ValueError('Verification requires complete nonempty passing evidence')
            if status == 'failed' and (not results or all(r['passed'] for r in results)):
                raise ValueError('Failed evaluation needs an observed failed fixture')
            if status == 'needs_evaluation' and all_passed:
                raise ValueError('Complete passing evidence has inconsistent status')
            self._append(state, 'evaluation', dict(id=capability_id, status=status, evidence=evidence))
            return _copy(self._capabilities(state)[capability_id])

    def progress_evidence(self, episode_ids):
        """Return trusted, scoped evidence for ambition progress.

        Episode finish text, tool results and model-written success flags never
        establish progress. Capabilities are deduplicated by specification ID;
        callers must also avoid reusing evidence across unrelated milestones.
        This read API does not grant a model access to outcome-writing methods.
        """
        if not isinstance(episode_ids, (list, tuple, set)) or any(
                not _nonempty(identifier) for identifier in episode_ids):
            raise ValueError('Evidence scope must contain episode IDs')
        selected = set(episode_ids)
        with self._locked():
            state = self._read()
            episodes = self._episodes(state)
            if selected - episodes.keys():
                raise KeyError('Evidence scope contains unknown episodes')
            objectives = []
            for event in state['events']:
                if event['kind'] != 'objective_outcome':
                    continue
                data = event['data']
                contract = data['evidence'].get('contract_id')
                if data['episode_id'] in selected and _nonempty(contract):
                    results = data['evidence'].get('results', [])
                    infrastructure_error = data['evidence'].get('infrastructure_error') is True
                    if isinstance(results, list):
                        infrastructure_error = infrastructure_error or any(
                            isinstance(result, dict) and result.get('status') == 'sandbox_error'
                            for result in results)
                    objectives.append(dict(episode_id=data['episode_id'],
                        success=data['success'], contract_id=contract,
                        infrastructure_error=infrastructure_error))
            proposal_ids = set()
            for identifier in selected:
                proposals = episodes[identifier].get('proposal_ids', [])
                if isinstance(proposals, list):
                    proposal_ids.update(p for p in proposals if isinstance(p, str))
            capabilities = []
            for identifier, record in self._capabilities(state).items():
                if identifier not in proposal_ids or not record['evaluations']:
                    continue
                evidence = record['evaluations'][-1]
                functional = {key: record['spec'].get(key) for key in
                              ('contract_id', 'input_schema', 'steps')}
                capabilities.append(dict(id=identifier, contract_id=evidence['contract_id'],
                                         status=record['status'],
                                         functional_sha256=_hash(functional)))
            return _copy(dict(objectives=objectives, capabilities=capabilities))

    def context(self):
        with self._locked():
            state = self._read()
            episodes = self._episodes(state)
            outcome_records = {e['data']['episode_id']: e['data'] for e in state['events'] if e['kind'] == 'objective_outcome'}
            outcomes = {key: value['success'] for key, value in outcome_records.items()}
            tools = {}
            failures = []
            objective_success = objective_failure = objective_pending = 0
            for episode_id, episode in episodes.items():
                # Episode flags are recorded observations; validated success only
                # comes from the separate trusted outcome record.
                outcome = outcomes.get(episode_id)
                if outcome is True:
                    objective_success += 1
                elif outcome is False:
                    objective_failure += 1
                    failures.append(dict(episode_id=episode_id, kind='objective', objective=episode.get('objective'), evidence=_bounded(outcome_records[episode_id]['evidence'])))
                else:
                    objective_pending += 1
                for observation in episode.get('tool_observations', []):
                    tool = observation['tool']
                    summary = tools.setdefault(tool, dict(observations=0, execution_success=0,
                        execution_failure=0, objective_success=0, objective_failure=0, objective_unknown=0))
                    summary['observations'] += 1
                    summary['execution_success' if observation['execution_success'] else 'execution_failure'] += 1
                    associated = outcome  # Association with trusted episode result; not causal attribution.
                    summary['objective_success' if associated is True else 'objective_failure' if associated is False else 'objective_unknown'] += 1
                    if not observation['execution_success']:
                        failures.append(dict(episode_id=episode_id, kind='tool_execution', tool=tool,
                                             error=observation.get('error'), objective=episode.get('objective')))
            preferences = [dict(tool=name, basis='observed_execution_success_rate_only',
                execution_success_rate=summary['execution_success']/summary['observations'],
                observations=summary['observations']) for name, summary in tools.items()]
            preferences.sort(key=lambda p: (-p['execution_success_rate'], -p['observations'], p['tool']))
            capabilities = self._capabilities(state)
            return dict(episodes=len(episodes), objective_success=objective_success,
                objective_failure=objective_failure, objective_pending=objective_pending,
                tools=tools, recent_failures=failures[-10:], tool_preferences=preferences,
                recent_episodes=[dict(episode_id=episode_id, objective=episode.get('objective'),
                    objective_success=outcomes.get(episode_id),
                    outcome_evidence=_bounded(outcome_records[episode_id]['evidence']) if episode_id in outcome_records else None,
                    tool_observations=[_bounded(o) for o in episode.get('tool_observations', [])[-6:]],
                    finish_message=_bounded(episode.get('finish_message')))
                    for episode_id, episode in list(episodes.items())[-5:]],
                tool_objective_basis='Association with trusted episode evaluation; not tool-level causal attribution',
                capabilities=[dict(id=c['id'], name=c['spec']['name'], description=c['spec']['description'],
                    status=c['status'], capability_sha256=c['capability_sha256']) for c in capabilities.values()],
                learning_mechanism='Persistent observations supplied to future planning; no model-weight updates',
                verification_scope='Only named evaluator contracts and their recorded fixtures')
