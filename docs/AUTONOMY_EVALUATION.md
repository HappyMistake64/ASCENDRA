# Continuation research and candidate evaluation

These are callable helpers in `ascendra.continuation_cycle`, not a scheduled service.

## Post-run research

`propose_next_steps(store, topic, decide=bounded_decider, urls=None, mode="self_improvement")`
fetches fresh evidence using existing bounded public-web research, persists it,
then uses the existing strictly validated proposal generator/store. Success yields
3–8 distinct cited proposals, one recommendation and `status: awaiting_selection`.
It never approves, queues or executes a proposal. Failed research is persisted
and returns `research_failed`. Model/validation errors propagate. The caller must
supply a bounded decider and journal this post-run step for restart deduplication.
This helper does not independently guarantee exactly-once calls. Evidence proves
provenance, not factual correctness; retrieved text is untrusted data.

## Candidate comparison

`evaluate_candidate(baseline, candidate, cases, evaluator=trusted_callback,
evaluator_id="suite-version-and-code-sha", repeats=3,
budget={"max_cost": 0, "max_seconds": 60}, min_gain=0.05, max_regression=0.0)`

The operator-owned callback receives `(artifact_path, case, budget, repeat)` and
returns finite numeric `score` (0–1, higher better), `cost` and `seconds`.
Candidates must never supply or modify the evaluator. Each invocation gets a
pristine temporary artifact copy, identical case/budget and alternating version
order. Reports reject malformed/over-budget outcomes, mutation of input artifacts,
links and oversized trees. Any case mean regression exceeding tolerance rejects
the candidate even if average improvement passes.

**Copies are not a security sandbox.** The trusted evaluator must isolate candidate
processes from production secrets, enforce wall-time/process/token/cost limits,
and measure results independently. A synchronous callback that hangs cannot be
preempted by this helper. Do not pass model-generated Python as evaluator code.
Maximum invocations are `2 * repeats * len(cases)`; resource budgets are per call.

Reports bind baseline/candidate hashes, case digest, evaluator ID, thresholds,
individual observations and gains. The report digest binds content but is not a
signature or authorization. Store reports in trusted storage. Repeated comparisons
are not statistical proof of general improvement; scoring and cost accuracy are
responsibilities of the trusted evaluator.

## Local-owner promotion registry

`initialize_versions(directory, baseline)` creates a local registry.
`promote_candidate(directory, baseline, candidate, report,
expected_current=hash, allow_promotion=True)` accepts an eligible **trusted** report,
checks its digest and both current artifact hashes, and atomically changes the
registry pointer. `rollback_version(directory, target_hash,
expected_current=hash, allow_rollback=True)` accepts only registered versions whose
bytes still match. A process lock serializes changes and compare-and-swap rejects
stale callers; pointer and history share one atomically replaced, fsynced file.

This is an OS-owner API, not remote authorization. Digest validation detects
accidental report alteration; it does not authenticate an adversarial report that
has been rehashed. Pass reports produced by the trusted evaluation call or read
from operator-controlled storage only. Keep the registry and version directories
operator-owned and immutable to candidate code. Cooperative locking does not
protect against malicious same-user processes changing files during promotion.

The registry does not restart workers, alter running Python imports, deploy or
modify the active installation. Production integration must resolve the registry
at controlled startup, independently authenticate policy, and run health checks.
Comparison reports continue to state `promoted: false`; successful pointer updates
are separately recorded in registry history.

## Practical CLI

```
python -m ascendra.evaluation_cli propose-next --data /path/to/state \
  --topic "Improve project verification" --url https://example.org/docs
python -m ascendra.evaluation_cli evaluate --baseline /path/to/baseline \
  --candidate /path/to/candidate --cases /path/to/cases.json \
  --trusted-evaluator /absolute/path/to/operator-evaluator
```

`propose-next` uses actual LocalDecider/Ollama, with one model-call budget and
persisted provider ledger. `evaluate` launches only the explicitly provided
operator executable; no shell or model-selected commands. Its stdin is JSON with
artifact path, case, budget and repeat, and stdout must be one JSON score/cost/time
object. It receives a minimal environment without inherited API keys and a fresh
working directory; stdout/stderr file size is limited, process-group timeout and
parent-measured elapsed time are enforced. Cost still requires a trustworthy
measurement from the evaluator. The executable runs with your OS permissions:
this is **not** OS isolation and does not restrict filesystem/network access.
The executable must itself provide sandboxing before running untrusted candidates.

## Verification

Run `python -m unittest tests.test_continuation_cycle -v` (10 tests).
Tests cover repeated isolation, alternating order, budget mutation resistance,
regressions, nonfinite scores, resource overruns, artifact mutation, links and
approval-free continuation. Research fixtures and evaluators are synthetic;
passing these tests does not demonstrate real model self-improvement.

Additional tests cover stale/concurrent promotion, report/artifact tampering,
rollback, and real execution of an explicit synthetic evaluator executable.

## Durable continuation worker

`ascendra.continuation_worker.schedule_after_run(child_queue, verified_parent,
topic, urls=None, enabled=True)` freezes a separately authorized research request
under deterministic `parent_id:research`. Without explicit `enabled=True` it does
nothing; the trusted parent must be completed with verified output. Use a dedicated
`data/continuation.sqlite3` queue so project workers cannot claim research tasks.

`python -m ascendra.continuation_worker --data /path/to/data --once` claims one
child, retrieves/persists evidence and invokes actual LocalDecider with a separate
budget of one call, 20,480 reserved tokens and 180 seconds. Research retrieval is
bounded by the existing 45-second limit; model timeout is at most 135 seconds and
the remaining total budget. Completed output contains the batch and the state
`awaiting_selection`; approval is never automatic.

The model reservation is persisted before invocation. If the process is lost
thereafter without a result checkpoint, recovery records `interrupted_uncertain`
and never silently repeats the potentially consumed call. A completed checkpoint
can be finalized after restart without another call. Failures are durable and
redact exception details. Local callbacks are test injection points, not model
supplied tools. The bridge owns external process termination and remote batch
publication. Local helper execution alone does not imply a dashboard upload.

`python -m unittest tests.test_continuation_worker -v` adds four synthetic tests:
explicit opt-in/verified parent/idempotency, persisted proposal batch, durable
failure, and no replay after an uncertain reserved call.
