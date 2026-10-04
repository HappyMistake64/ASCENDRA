import json
from pathlib import Path
from .models import TaskSpec

class BenchmarkRegistry:
    def __init__(self, root: Path):
        self.root = root

    def load(self):
        m = json.loads((self.root / 'manifest.json').read_text())
        out = []
        for t in m['tasks']:
            out.append(TaskSpec(
                t['id'], t['description'], self.root / 'tasks' / t['id'],
                t['test_command'], t.get('split', 'visible'), t.get('timeout_s', 10),
                int(t.get('eval_group', 0)), t.get('hidden_globs', ['.ascendra_hidden/**'])
            ))
        return out
