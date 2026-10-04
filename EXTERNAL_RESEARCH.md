# Frozen-strategy external replication

This study compares the existing `g0-baseline` with `g1-4e1dee6d`, without mutating
either prompt or changing the original experiment's lineage or decision.

Twenty HumanEval tasks are selected by sorting SHA-256(seed + task ID) at the
pinned upstream commit. The fixed seed is `ASCENDRA-external-humaneval-20-v1`.
No task is dropped, substituted, or selected using its test result. Public task
prompts go to the model; reference solutions and tests remain evaluator-only.

Each strategy gets three independent completions per task with `gpt-6-astra`,
reasoning `low`, and the `codex_subscription` provider. The 120 planned solve
calls are paired by task and replicate. Which strategy goes first is balanced
within each replicate. There is no adaptive stopping or outcome-based retry.

The primary unit is the task, with three repetitions clustered within each task.
Verified external gain requires the existing repeated promotion gate, no
aggregate task regression, and a one-sided task-level sign-test p-value at most
0.05. The study also reports a fixed-seed percentile bootstrap over the 20 task
clusters. A public benchmark may already have appeared in training; these tasks
are unused in this experiment, not guaranteed novel to the model. Function
completion is narrower than repository engineering and does not demonstrate RSI.

Before any model solutions, all 20 canonical solutions must pass and all 20
unimplemented stubs must fail the same wrapper. A failed control blocks the study.
Generated code runs in a fresh bubblewrap namespace with no network, credentials,
host workspace or writable evaluator files, and with CPU/memory limits. Provider
failures and isolation failures invalidate the run instead of becoming task losses.

```bash
python3 -m ascendra.external_research prepare
./run_external_research.sh
```

The preregistration, source hashes, exact task IDs and schedule are written under
`.ascendra/external-humaneval-v1/` before execution. Running refuses to overwrite
existing experimental evidence. Do not remove a partial database to obtain a
more favorable result. Diagnose infrastructure failures and register a new study.

Source: https://github.com/openai/human-eval/tree/6d43fb980f9fee3c892a914eda09951f772ad10d
Paper: Chen et al., Evaluating Large Language Models Trained on Code (2021),
https://arxiv.org/abs/2107.03374
