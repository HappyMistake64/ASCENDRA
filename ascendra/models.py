from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class TaskSpec:
    id: str
    description: str
    source_dir: Path
    test_command: list[str]
    split: str = "visible"
    timeout_s: int = 10
    eval_group: int = 0
    hidden_globs: list[str] = field(default_factory=lambda: [".ascendra_hidden/**"])

@dataclass
class Strategy:
    id: str
    generation: int
    parent_id: str | None
    system_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskResult:
    task_id: str
    strategy_id: str
    solved: bool
    returncode: int
    duration_s: float
    stdout: str = ""
    stderr: str = ""
    changed_files: list[str] = field(default_factory=list)
    error: str | None = None
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0

@dataclass
class EvalSummary:
    strategy_id: str
    total: int
    solved: int
    solve_rate: float
    visible_total: int
    visible_solved: int
    holdout_total: int
    holdout_solved: int
    duration_s: float
    results: list[TaskResult]
    def to_dict(self): return asdict(self)
