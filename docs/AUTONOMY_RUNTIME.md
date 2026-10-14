# Durable ASCENDRA runtime

## Implemented scope

Static frontend projects (index.html plus optional app.js/styles.css), explicit local Ollama Qwen provider. This executor does not use a visitor's selected cloud router model. Queue ownership, immutable snapshots and independently supplied browser contracts precede generation. Default smoke contracts establish only basic rendering; they do not certify all requested behavior.

Dashboard approval -> D1 job -> outbound execution bridge -> per-job durable SQLite journal -> local model planner/builders -> namespace-isolated browser checks -> bounded repairs -> immutable artifacts/report -> owner-private preview and chosen-version pointer. Optional post-run research uses a separate fixed budget and returns proposals awaiting selection.

## Start

Install ASCENDRA, Node, Chromium, Bubblewrap and Playwright. Set ASCENDRA_PLAYWRIGHT_PACKAGE to the package.json next to the installed Playwright node_modules when not using this workspace layout. Ollama must serve an installed non-cloud model on loopback. ASCENDRA_MAX_WORKERS defaults to 2 and bounds both implementation and verification concurrency; max_agents is the request, not a guarantee of 50 available CPUs/models.

Local command:

```sh
python -m ascendra.execution_cli --data /absolute/state enqueue --owner local-owner --key unique-request --description 'Build a counter with #count, #increment and #reset' --contract examples/contracts/counter.json --strategy planned --max-calls 3 --max-tokens 61440 --max-agents 2
python -m ascendra.execution_cli --data /absolute/state work
```

The remote bridge is `python -m ascendra.execution_bridge`. Supply a single JSON object on private stdin with site, service_token, bridge_token, data and optional model. Credentials stay in process memory, are never persisted by the bridge, and must not appear in shell arguments or logs. The Sites service credential and runtime ROUTER_BRIDGE_TOKEN must match the deployed Site. The existing ollama-bridge.py separately serves interactive router requests.

## Recovery and limits

Leases and fencing prevent stale result commits. Idempotency keys deduplicate enqueue. Candidate/test checkpoints survive restarts, and hashes detect mutation. A reserved model call with no committed candidate fails as uncertain instead of replaying and potentially repeating billable work. This is deliberately not an exactly-once guarantee for external requests.

A planned run reserves one planner call and bounded independent implementation alternatives; each has its own process and ledger plus shared persisted reservations. Candidates remain separate; no blind concurrent file merge. Passing candidates may enter the normal repair pipeline without repeating model generation. Verification scenarios use independent processes under Bubblewrap with no host network, no ambient credentials, read-only project and only a dedicated writable report directory. Host process supervision and cgroup memory/process limits are still needed in production.

Each model call conservatively reserves 20,480 tokens. Call and token limits are both enforced. Generated reports distinguish tests from generation and never mark an untested candidate verified. A stopped run terminates subprocess groups; an upstream model request already accepted may continue server-side. A completed application's follow-up research can be stopped independently.

## Post-run research

Explicit opt-in (visible default checked in dashboard): one model call, 20,480 reserved tokens, 180 seconds. Fresh sources and 3..8 distinct proposals are required. Research failures and uncertain interrupted calls are recorded; they never create invented proposals or autoapprove subsequent work. A follow-up batch is imported idempotently into the dashboard. Publication validates source freshness and distinct proposal titles/IDs.

## Versions and self-improvement

The dashboard chosen-version pointer and rollback apply to owner-private tested static artifacts. They are not deployment of arbitrary generated services to external production infrastructure. User data migrations are not covered.

Evaluation tooling compares immutable baseline/candidate copies with a trusted independent evaluator, repeated measurements, regression and budget checks. Local promotion/rollback registry requires explicit operator policy and current-hash CAS. A positive report changes only a version pointer; it does not replace or restart the running ASCENDRA installation. Full unattended promotion of the core is not enabled. Choose an independent benchmark and reviewed service rollout policy before enabling that path.

## Continuous hosting

`deploy/ascendra-executor.service` is a template, not an installed service. It applies cgroup limits and restart supervision after installation on an owned persistent server with required dependencies. It supervises the local queue; remote bridge credentials need a supported service credential delivery mechanism. This chat workspace does not establish 24/7 availability. The current remote bridge intentionally stops after 24 hours; closing/stopping the environment ends its compute availability.

## Observed validation (2026-10-14)

- Real Qwen sequential counter run: 1 model call, 12 browser checks passed, ~76 seconds; no hand-edit of generated output.
- Real Qwen planned counter run: planner + 2 independent builders, 3 model calls, selected result passed 12 checks, ~165 seconds; no hand-edit.
- Evidence: /workspace/ascendra-autonomy-e2e and /workspace/ascendra-autonomy-*-result.json (local evidence paths, not packaged production assets).
- Earlier offline-provider attempt failed honestly and remains in the queue history.
- Unit suites include fixtures; they are not represented as live model or production-user runs.
