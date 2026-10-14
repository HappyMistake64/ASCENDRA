# ASCENDRA Studio — first working slice

Studio adds a local workflow to the existing capability runtime:
fresh public-web research → at least three cited proposals → explicit selection
and approval → an isolated project or self-improvement candidate.

Install with `python3 -m pip install -e .`, or use
`python3 -m ascendra.studio_cli` instead of `ascendra-studio`.
Model operations default to local Ollama with `qwen2.5-coder:7b`. No API key or
per-token API fee is required; your machine supplies the compute. Install Ollama,
start its local server with cloud features disabled, then pull the model:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
# In another terminal:
ollama pull qwen2.5-coder:7b
ascendra-studio --data /workspace/ascendra-studio-data doctor
```

The local model is smaller and less capable than frontier models. CPU generation
can take minutes. Plan for roughly 5 GB of model storage plus runtime/context RAM.
Do not launch 50 local models at once. Start with one worker and measure results.
The local adapter accepts loopback IP addresses only, disables native tools,
validates structured output and preserves call/token accounting. Failures consume
budget; there is no hidden remote fallback or automatic regeneration. Large inputs
are rejected rather than silently truncated. API fee is zero; total hardware and
electricity costs are not measured.

Use `--provider codex` before the subcommand to opt into the existing official
Codex/ChatGPT transport explicitly. Its authentication and sandbox requirements
still apply. `--model` overrides the model for the selected provider. This changes
Studio only: historical benchmark constants and `ascendra-agent` defaults remain
unchanged. No simulated model fallback is used.

Local validation on 2026-10-14 used Ollama 0.40.4 and the 7B model manifest
`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`:
325 offline tests passed. A real model-generated counter app passed browser checks
for initial zero, two increments, reset, and absence of JavaScript errors.
A fresh MDN source produced three proposals passing the original validators.
The first proposal attempt invented a URL and was rejected; generation was then
constrained to observed source URLs, with a new recorded call. Four local calls
used 6,778 reported tokens in total. No API fee was charged; hardware costs were
not measured. These small checks do not establish general programming competence
or semantic correctness of arbitrary research proposals. The Sites executor is
still not connected to this local model.

```sh
ascendra-studio --data /workspace/ascendra-studio-data propose \
  "A small accessible study planner" --mode project \
  --url https://developer.mozilla.org/en-US/docs/Web/Accessibility
ascendra-studio --data /workspace/ascendra-studio-data status
ascendra-studio --data /workspace/ascendra-studio-data approve BATCH_ID PROPOSAL_ID --max-calls 10
ascendra-studio --data /workspace/ascendra-studio-data execute JOB_ID
```

Keep the state directory outside source projects. Preserve/back up this directory:
it contains the SQLite approval journal, evidence, model-call ledgers and generated
projects. Workspace replacement can delete local state; SQLite is not remote hosting.

Research errors block proposals. Evidence is dated and proposals cite only retrieved
sources. Structural validation does not prove the sources true or ideas genuinely
novel. User approval, not the model recommendation, creates executable jobs.
Budgets cannot be enlarged by repeating approval. A job can be claimed once;
`completed` means the execution finished, **not verified improvement**.

Project mode currently generates static HTML/CSS/JS applications, without executing
generated scripts. Review output before serving it locally or deploying it.
Structural checks are not a browser/functional acceptance test.

Self-improvement mode needs explicit scope:

```sh
ascendra-studio --data /workspace/ascendra-studio-data execute JOB_ID \
  --project /workspace/ASCENDRA-github --allow-write ascendra/example.py
```

This copies public project files to an isolated candidate and uses existing bounded
host tools. It never modifies the installed source project or automatically promotes
the candidate. Independent before/after evaluation and explicit promotion remain
required. Model weights are not trained.

## Remaining integration

- The current Studio executor is single-worker; `max_agents` is a reserved ceiling,
  not a promise that Studio launches 50 workers. The separate existing autonomous
  CLI supports multi-worker runs.
- The existing Sites observatory is not yet connected to Studio approvals or jobs.
- Persisted pause/resume states are not a process-pause implementation. The Studio
  CLI can cancel queued jobs only. Interrupted running jobs need operator recovery;
  they are deliberately not retried automatically, to avoid duplicate side effects.
- Full-stack generation, arbitrary algorithm evaluation, browser acceptance tests,
  supervised promotion/rollback, durable hosted workers and remote backups remain
  follow-on work. No paid infrastructure is provisioned by this change.
