"""Codex subscription transport with repository isolation and tool-use rejection."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .provider import CodexCLIProvider
from .agent import _is_private


class ProviderBlocked(RuntimeError):
    pass


class SubscriptionProvider(CodexCLIProvider):
    DISABLED_HOST_NOTICE = ('Code Mode is unavailable because code-mode host is disabled. '
                            'Code mode will fail closed; enable `features.code_mode_host` '
                            'and install `codex-code-mode-host`.')
    # Disable external capabilities and local execution before starting the model.
    DISABLED = ('apps', 'plugins', 'remote_plugin', 'multi_agent', 'multi_agent_v2',
                'shell_tool', 'unified_exec', 'code_mode', 'code_mode_host',
                'browser_use', 'computer_use', 'image_generation', 'view_image',
                'hooks', 'memories', 'skill_search', 'tool_suggest', 'sleep_tool')

    def __init__(self, *, root, model='gpt-6-astra', effort='low', timeout_s=180):
        super().__init__(model=model, effort=effort, timeout_s=timeout_s)
        self.root = Path(root).resolve()
        self.bwrap = shutil.which('bwrap')
        if not self.bwrap:
            raise ProviderBlocked('Missing prerequisite: bubblewrap (bwrap) for evaluator isolation.')
        if self.root == Path('/') or self.root == Path('/tmp'):
            raise ProviderBlocked('Repository root must be a dedicated directory.')
        self.call_records = []
        self.event_sink = None
        self.codex_directory = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        self.auth_file = self.codex_directory / 'auth.json'
        if not self.auth_file.is_file():
            raise ProviderBlocked('Codex file authentication is required; run codex login --device-auth.')

    def isolated_command(self, command, scratch):
        # Hide the entire repository (including transport bundles and evidence),
        # all other temporary workspaces, and host processes/file descriptors.
        return [self.bwrap, '--die-with-parent', '--unshare-pid', '--unshare-ipc',
                '--unshare-uts', '--ro-bind', '/', '/', '--tmpfs', str(self.root),
                '--tmpfs', str(Path.home()), '--tmpfs', str(self.codex_directory),
                '--ro-bind', str(self.auth_file), str(self.auth_file),
                '--tmpfs', '/tmp', '--proc', '/proc', '--dev', '/dev',
                '--bind', str(scratch), str(scratch), '--chdir', str(scratch),
                '--', *command]

    def verify_isolation(self):
        with tempfile.TemporaryDirectory(prefix='ascendra-isolation-', dir=self.root) as private, \
                tempfile.TemporaryDirectory(prefix='ascendra-codex-') as scratch:
            marker = Path(private) / 'sentinel'
            marker.write_text('artificial isolation sentinel')
            script = ('from pathlib import Path; import os; '
                      f'assert not Path({str(marker)!r}).exists(); '
                      f'assert list(Path({str(self.root)!r}).iterdir()) == []; '
                      f'assert Path.cwd() == Path({scratch!r}); '
                      'assert os.getppid() <= 1')
            cp = subprocess.run(self.isolated_command(['python3', '-c', script], scratch),
                                capture_output=True, text=True, timeout=15)
            if cp.returncode:
                raise ProviderBlocked('Filesystem/process isolation probe failed.')

    def _exec(self, prompt, schema):
        start = time.monotonic()
        request = json.loads(prompt)
        operation = ('mutate' if 'parent_strategy' in request else
                     'solve' if 'public_files' in request else 'preflight')
        record = {'provider': 'codex_subscription', 'model': self.model,
                  'reasoning_effort': self.effort, 'operation': operation,
                  'request_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                  'input_tokens': None, 'output_tokens': None, 'total_tokens': None,
                  'cost': None, 'status': 'error', 'error': None, 'tool_calls': 0}
        self._add_usage(calls=1)
        try:
            with tempfile.TemporaryDirectory(prefix='ascendra-codex-') as td:
                scratch = Path(td)
                schema_path, output_path = scratch / 'schema.json', scratch / 'last.json'
                schema_path.write_text(json.dumps(schema))
                cmd = [self.binary, 'exec', '--json', '--ephemeral', '--skip-git-repo-check',
                       '--ignore-user-config', '--ignore-rules', '--sandbox', 'read-only',
                       '--model', self.model, '-c', f'model_reasoning_effort="{self.effort}"',
                       '-c', 'web_search="disabled"', '-c', 'approval_policy="never"',
                       '--output-schema', str(schema_path), '-o', str(output_path)]
                for feature in self.DISABLED:
                    cmd.extend(['--disable', feature])
                cmd.append('-')
                cp = subprocess.run(self.isolated_command(cmd, scratch), input=prompt,
                                    capture_output=True, text=True, timeout=self.timeout_s)
                completed = False
                for line in cp.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get('type') == 'turn.completed':
                        completed = True
                        usage = event.get('usage') or {}
                        record['input_tokens'] = usage.get('input_tokens')
                        record['output_tokens'] = usage.get('output_tokens')
                        if all(type(record[k]) is int for k in ('input_tokens', 'output_tokens')):
                            record['total_tokens'] = record['input_tokens'] + record['output_tokens']
                        self._add_usage(input_tokens=record['input_tokens'], output_tokens=record['output_tokens'])
                    if event.get('type', '').startswith('item.'):
                        item = event.get('item') or {}
                        kind = item.get('type')
                        if kind == 'error' and item.get('message') == self.DISABLED_HOST_NOTICE:
                            record['code_mode_disabled'] = True
                            continue
                        if kind not in ('agent_message', 'reasoning'):
                            record['tool_calls'] += 1
                if cp.returncode:
                    # Do not copy arbitrary provider output into a future model prompt.
                    reason = 'authentication rejected' if '401' in cp.stderr else 'Codex execution failed'
                    raise ProviderBlocked(f'{reason} (exit {cp.returncode}).')
                if record['tool_calls']:
                    raise ProviderBlocked('Tool activity invalidated this provider response.')
                if not completed or not output_path.exists():
                    raise ProviderBlocked('Codex did not complete a structured response.')
                raw = output_path.read_text()
                record['response_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
                result = json.loads(raw)
                record['status'] = 'completed'
                return result
        except subprocess.TimeoutExpired:
            record['error'] = 'Codex request timed out.'
            raise ProviderBlocked(record['error']) from None
        except ProviderBlocked as exc:
            record['error'] = str(exc)
            raise
        except (ValueError, OSError):
            record['error'] = 'Invalid structured response or provider process failure.'
            raise ProviderBlocked(record['error']) from None
        finally:
            record['duration_s'] = time.monotonic() - start
            self.call_records.append(record)
            if self.event_sink:
                self.event_sink('provider_call', record)

    def preflight(self):
        self.verify_isolation()
        result = self._exec(json.dumps({'instruction': 'Connectivity check only. Return ready=true.'}),
                            {'type': 'object', 'properties': {'ready': {'type': 'boolean'}},
                             'required': ['ready'], 'additionalProperties': False})
        if result != {'ready': True}:
            raise ProviderBlocked('Provider readiness response was invalid.')
        return result

    def propose_edits(self, *, prompt, task_id, description, files):
        if any(_is_private(Path(path)) or Path(path).is_absolute() or '..' in Path(path).parts
               for path in files):
            raise ProviderBlocked('Private or invalid file snapshot rejected before transmission.')
        schema = {'type': 'object', 'properties': {'files': {
            'type': 'array', 'items': {'type': 'object', 'properties': {
                'path': {'type': 'string'}, 'content': {'type': 'string'}},
                'required': ['path', 'content'], 'additionalProperties': False}}},
            'required': ['files'], 'additionalProperties': False}
        result = self._exec(json.dumps({
            'role': 'ASCENDRA software-engineering candidate', 'strategy': prompt,
            'task_id': task_id, 'task': description, 'public_files': files,
            'rules': ['Do not use any tools. Work only from the supplied public files.',
                      'Return complete replacements only for supplied files needing changes.',
                      'Prefer the smallest correct general fix and preserve unrelated behavior.'],
        }), schema)
        if not isinstance(result, dict) or set(result) != {'files'} or not isinstance(result['files'], list):
            raise ProviderBlocked('Invalid structured file replacements.')
        edits = {}
        for edit in result['files']:
            if (not isinstance(edit, dict) or set(edit) != {'path', 'content'}
                    or not isinstance(edit['path'], str) or edit['path'] not in files
                    or not isinstance(edit['content'], str) or edit['path'] in edits):
                raise ProviderBlocked('Private, unknown, duplicate, or malformed file edit rejected.')
            edits[edit['path']] = edit['content']
        return edits
