# Running with a ChatGPT subscription

This provider uses the official Codex CLI login, not the separately billed OpenAI API.
Requirements: Python 3.11+, the Codex CLI, bubblewrap, and subscription access to the
exact requested model. No API key is needed.

```bash
codex login --device-auth
python3 -m ascendra.cli doctor --provider codex_subscription --model gpt-6-astra --effort low
./run_real_subscription.sh
```

The run pins `real_v1`, `gpt-6-astra`, `low`, two possible generations and three
paired replicates. The provider identifier is `codex_subscription`, a different
configuration from the original `codex_cli` path. Model selection is explicit;
this adapter never substitutes a different identifier. The CLI does not expose
the backend model revision in its JSON event stream, so records identify the
requested model rather than claiming independent verification of that revision.

Before creating or archiving experimental evidence, `evolve` checks filesystem
isolation and performs a real, neutral model request. Failed preflight reports
`BLOCKED_NESTED_PROVIDER`. Use `codex login --device-auth` again if login is rejected.
The CLI login status alone is not sufficient evidence of working authentication.

The provider process cannot see the repository, its transport bundle, evaluator
workspaces, other temporary directories, or host processes through `/proc`.
Its home and Codex state are temporary; the existing authentication file is bound
read-only at its original location. The model receives serialized public files.
Execution, connectors, plugins and other capabilities are disabled; any tool
activity in the event stream invalidates the response. The CLI may emit its
specific Code Mode-disabled notice; that notice is recorded, not counted as a
tool execution. Unknown activity remains a failure.

Only replacements of supplied public files are accepted. Hidden directories are
filtered recursively, including symlink aliases. Mutation feedback contains task
outcomes, not evaluator stdout, stderr, source snippets or tracebacks. Evaluator
output stays in the local evidence store and is not passed to the provider.

The framework rejects any aggregate task regression, including visible tasks,
and always applies the Wilson lower-bound check. A rejected G1 ends the recursive
run; G2 is attempted only after G1 is promoted. Strategy IDs cannot be overwritten.

Evidence is under `.ascendra/`: unique preflight reports, SQLite evidence, JSON
export, and detailed status. Provider-call events record operation, model setting,
request/response hashes, reported tokens, duration, errors and tool activity for
solves, mutations and preflight. Unknown tokens and cost remain null in these
events; older task-level zero-valued cost fields do not mean measured free usage.
Unit tests use artificial sentinels and mocks; they are not experimental evidence.

Provider isolation does not make arbitrary generated Python a secure adversarial
evaluation environment. The current local benchmark runner remains a limitation
for claims beyond the controlled exploratory experiment.
