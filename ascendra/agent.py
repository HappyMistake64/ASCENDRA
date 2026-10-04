from pathlib import Path

def _is_private(path, hidden_globs=None):
    # pathlib's match('.ascendra_hidden/**') does not cover deeper descendants.
    # Protect the reserved directory at every depth, including the directory itself.
    if '.ascendra_hidden' in path.parts:
        return True
    for pattern in hidden_globs or []:
        if path.match(pattern):
            return True
        if pattern.endswith('/**'):
            prefix = pattern[:-3]
            if any(parent.match(prefix) for parent in (path, *path.parents)):
                return True
    return False

class EvolutionAgent:
    def __init__(self, provider):
        self.provider = provider

    def _files(self, root, hidden_globs=None):
        hidden_globs = hidden_globs or []
        out = {}
        for p in root.rglob('*'):
            rel = p.relative_to(root)
            if _is_private(rel, hidden_globs) or any(
                part.is_symlink() for part in (p, *p.parents) if part != root
            ):
                continue
            if not p.is_file() or p.stat().st_size >= 100000:
                continue
            if p.suffix in {'.py', '.txt', '.md', '.json', '.toml'}:
                out[str(rel)] = p.read_text(errors='replace')
        return out

    def solve(self, strategy_prompt, task_id, description, workspace, hidden_globs=None):
        before = self._files(workspace, hidden_globs)
        edits = self.provider.propose_edits(
            prompt=strategy_prompt, task_id=task_id, description=description, files=before
        )
        changed = []
        for rel, content in edits.items():
            if _is_private(Path(rel), hidden_globs):
                raise ValueError(f'hidden evaluator path rejected: {rel}')
            target = (workspace / rel).resolve()
            if workspace.resolve() not in target.parents:
                raise ValueError('path traversal rejected')
            # Never allow the model to alter evaluator-private files.
            relpath = target.relative_to(workspace.resolve())
            if _is_private(relpath, hidden_globs):
                raise ValueError(f'hidden evaluator path rejected: {rel}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            changed.append(rel)
        return changed
