import json
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

class Provider(ABC):
    def usage_snapshot(self):
        return dict(getattr(self, '_usage', {'model_calls':0,'input_tokens':0,'output_tokens':0}))
    def _add_usage(self, calls=0, input_tokens=0, output_tokens=0):
        if not hasattr(self, '_usage'): self._usage={'model_calls':0,'input_tokens':0,'output_tokens':0}
        self._usage['model_calls'] += int(calls or 0); self._usage['input_tokens'] += int(input_tokens or 0); self._usage['output_tokens'] += int(output_tokens or 0)
    @abstractmethod
    def propose_edits(self, **kwargs): ...
    def mutate_prompt(self, *, parent_prompt, failure_summary, generation):
        return parent_prompt + '\nReview prior failures. Prefer minimal, testable changes.'

class CommandProvider(Provider):
    def __init__(self, command, timeout_s=120):
        self.command = command
        self.timeout_s = timeout_s
    def _call(self, payload):
        cp = subprocess.run(self.command, input=json.dumps(payload), text=True, capture_output=True, timeout=self.timeout_s)
        if cp.returncode:
            raise RuntimeError(cp.stderr[-4000:])
        return json.loads(cp.stdout)
    def propose_edits(self, **kw):
        return self._call({'op': 'solve', **kw}).get('files', {})
    def mutate_prompt(self, **kw):
        return self._call({'op': 'mutate', **kw}).get('prompt', kw['parent_prompt'])

class CodexCLIProvider(Provider):
    """Real provider using the official Codex CLI in non-interactive, ephemeral mode.

    Codex never receives the evaluator workspace path. It receives only the explicit
    public file snapshot, which keeps `.ascendra_hidden/**` tests outside model context.
    """
    def __init__(self, model=None, effort=None, timeout_s=180):
        self.binary = shutil.which('codex')
        if not self.binary:
            raise RuntimeError('Codex CLI not found in PATH. Install/login to Codex CLI first.')
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s

    def _exec(self, prompt, schema):
        with tempfile.TemporaryDirectory(prefix='ascendra-codex-') as td:
            td = Path(td)
            schema_path = td / 'schema.json'
            output_path = td / 'last.json'
            schema_path.write_text(json.dumps(schema))
            cmd = [
                self.binary, 'exec', '--json', '--ephemeral', '--skip-git-repo-check',
                '--ignore-user-config', '--sandbox', 'read-only',
                '--output-schema', str(schema_path), '-o', str(output_path), '-'
            ]
            if self.model:
                cmd[2:2] = ['--model', self.model]
            if self.effort:
                # Codex config override; ignored by older versions only if unsupported.
                cmd[2:2] = ['-c', f'model_reasoning_effort="{self.effort}"']
            cp = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                                timeout=self.timeout_s, cwd=td)
            if cp.returncode:
                raise RuntimeError(f'codex exec failed ({cp.returncode}): {cp.stderr[-5000:]}')
            inp=out=0
            for line in cp.stdout.splitlines():
                try: event=json.loads(line)
                except json.JSONDecodeError: continue
                if event.get('type') == 'turn.completed':
                    usage=event.get('usage') or {}; inp += int(usage.get('input_tokens') or 0); out += int(usage.get('output_tokens') or 0)
            self._add_usage(1, inp, out)
            raw = output_path.read_text().strip() if output_path.exists() else cp.stdout.strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise RuntimeError(f'Codex returned non-JSON final output: {raw[-3000:]}') from e

    def propose_edits(self, *, prompt, task_id, description, files):
        schema = {
            'type': 'object',
            'properties': {'files': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
            'required': ['files'], 'additionalProperties': False,
        }
        request = {
            'role': 'ASCENDRA software-engineering candidate',
            'strategy': prompt,
            'task_id': task_id,
            'task': description,
            'public_files': files,
            'rules': [
                'Return complete replacement content only for files that must change.',
                'Do not invent hidden tests or evaluator files.',
                'Prefer the smallest correct general fix.',
                'Do not return commentary outside the required JSON schema.',
            ],
        }
        result = self._exec(json.dumps(request, indent=2), schema)
        return result.get('files', {})

    def mutate_prompt(self, *, parent_prompt, failure_summary, generation):
        schema = {
            'type': 'object',
            'properties': {'prompt': {'type': 'string'}},
            'required': ['prompt'], 'additionalProperties': False,
        }
        request = {
            'role': 'ASCENDRA strategy mutator',
            'generation': generation,
            'parent_strategy': parent_prompt,
            'verified_failure_evidence': failure_summary,
            'objective': 'Produce a successor strategy that generalizes from verified failures while preserving solved behavior.',
            'constraints': [
                'Do not mention benchmark task IDs or memorize task-specific answers.',
                'Prefer reusable reasoning/process improvements.',
                'Keep the strategy concise and operational.',
            ],
        }
        return self._exec(json.dumps(request, indent=2), schema)['prompt']

class DemoProvider(Provider):
    '''Offline deterministic provider for plumbing tests only; never research evidence.'''
    def __init__(self, level=0): self.level = level
    def propose_edits(self, *, prompt, task_id, description, files):
        import re
        m = re.findall(r'Generation (\d+)', prompt)
        level = max([self.level] + [int(x) for x in m])
        edits = {}
        for path, src in files.items():
            dst = src
            if level >= 0: dst = dst.replace('return a - b  # BUG_ADD', 'return a + b  # fixed')
            if level >= 1: dst = dst.replace('return a + b  # BUG_MUL', 'return a * b  # fixed')
            if level >= 2: dst = dst.replace('return min(values)  # BUG_MAX', 'return max(values)  # fixed')
            if dst != src: edits[path] = dst
        return edits
    def mutate_prompt(self, *, parent_prompt, failure_summary, generation):
        return parent_prompt + f'\nGeneration {generation}: expand repair coverage using verified failures.'
