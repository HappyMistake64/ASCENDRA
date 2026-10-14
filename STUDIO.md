# ASCENDRA Studio — first working slice

Studio adds a local workflow to the existing capability runtime:
fresh public-web research → at least three cited proposals → explicit selection
and approval → an isolated project or self-improvement candidate.

Install with `python3 -m pip install -e .`, or use
`python3 -m ascendra.studio_cli` instead of `ascendra-studio`.
Model operations require the existing official Codex/ChatGPT authentication and
isolation prerequisites. No simulated model fallback is used.

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
