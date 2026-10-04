# ASCENDRA Masterplan

## Mission
ASCENDRA is a local-first experimental platform for measurable recursive improvement of software-engineering agents.

Core question: Can generation G(n) produce G(n+1) that performs better on isolated, previously unseen tasks under equal budgets, and can the accepted successor repeat that process?

## Non-negotiable rule
CHANGE != IMPROVEMENT. A candidate is promoted only by an independent evaluator.

## Success ladder
- A0 Measurement: reproducible benchmark registry, baseline, raw metrics.
- A1 Isolation: per-run disposable workspaces, time limits, command allow-list, audit log.
- A2 Evaluator: visible/holdout split, paired comparison, regression detection, promotion policy.
- A3 Evolution Agent: provider-neutral agent reads a task workspace and proposes file edits.
- A4 Mutation: parent strategy produces candidate strategies from failure evidence.
- A5 Selection: candidate vs champion on equal tasks/budgets; deterministic decision.
- A6 Recursion: promoted generation becomes parent of the next generation.
- A7 Autonomous Evolution: bounded multi-generation loop with stop conditions and rollback.

## Evidence required for an RSI-style claim
1. G0 baseline recorded.
2. G0 creates or causes creation of G1.
3. G1 beats G0 on holdout tasks under equal constraints.
4. G1 becomes champion.
5. G1 creates or causes creation of G2.
6. G2 beats G1 on a fresh/rotated holdout.
7. Full lineage, budgets, failures and regressions remain auditable.

Anything less is an agent-improvement experiment, not evidence of recursive improvement.

## Metrics
Primary: solved rate, holdout solved rate, regressions.
Secondary: first-pass success, repair success, wall time, model calls, input/output tokens, estimated cost, changed files.
Guardrails: timeout count, forbidden-path attempts, command violations, evaluator errors.

## Promotion policy v0.1
Candidate must have holdout solve-rate delta >= 0.05, zero regressions on tasks the champion solved, and cost ratio <= 1.20. Raw metrics are always stored.

## Milestones
v0.1 Evidence Core -> v0.2 Agent Runtime -> v0.3 Evolution -> v0.4 Recursion -> v0.5 Dashboard -> v0.6 Research Mode -> v1.0 reproducible evidence.

## v0.3 implementation status (2026-10-03)
- [x] A0 reproducible benchmark/evidence core
- [x] A1 disposable task workspaces + command allow-list
- [x] A2 pairwise evaluator + regression gate + rotating H1/H2 holdouts
- [x] A3 provider-neutral evolution agent
- [x] A3 real Codex CLI provider integration
- [x] A4 evidence-driven strategy mutation
- [x] A5 deterministic promotion/rejection
- [x] A6 bounded recursive lineage G0 -> G1 -> G2
- [x] A7 bounded multi-generation execution loop
- [x] hidden evaluator test isolation
- [x] local evidence dashboard/export
- [ ] real Codex run in the target user's authenticated environment
- [x] Codex model-call and token accounting from JSONL traces
- [ ] versioned monetary cost accounting
- [x] repeated paired local evaluation + confidence interval
- [x] checkpoint/rollback evidence events
- [ ] large external repository benchmark + independent statistical replication

The unchecked items are required before a strong research claim. They are not silently replaced by synthetic results.
