# ASCENDRA V4: validated diagnostics and conditional repair

V4 implements the next development experiment from `IMPROVEMENT_PLAN.txt`.
It improves the workflow around the requested `gpt-6-astra` model, with `low`
reasoning, through the existing isolated Codex subscription provider. It does
not train model weights or promote the original G0/G1/G2 lineage.

## Run

```bash
python3 -m unittest discover -v
python3 -m ascendra.method_research_v4 prepare
python3 -m ascendra.method_research_v4 verify
./run_method_research_v4.sh
python3 -m ascendra.method_research_v4 status
```

Preparation validates public diagnostic bundles before materializing evaluator
cases. Registration freezes the source files, public files, bundle contents,
private-case hashes, prompts, resource limits and development schedule. Code
changes after registration fail verification. Keep old studies intact; a change
requires a fresh study namespace and registration.

## Two policies

Both policies use the same first instruction and public diagnostic suite.
`best_of_two` generates two independent programs; `adaptive_repair` generates
one and requests one repair only after a verified failure. Diagnostics include
public examples and independently checked task-specific cases. Execution errors
and timeouts are reproduced before driving repair. Diagnostic infrastructure
errors stop the trial rather than being scored as incorrect programs.

Selection uses most passing controls, with all controls weighted equally and
ties choosing the first program. The program is frozen before private grading.
Repair feedback is public only and bounded by the controller. Expected private
outputs never enter the provider snapshot or candidate filesystem.

## Pilot and confirmation

The executable default is a 12-task development pilot using previously exposed
problems. It can establish whether the implementation works and reveal how
often diagnostics trigger useful repairs. It cannot establish a held-out gain.
The protocol module separately enforces a complete 40-task fresh confirmation
registration, paired comparisons, no task regressions and the specified
statistical gates. Forty independently validated fresh diagnostic bundles are
required before that experiment is registered; they are not fabricated or
replaced by a development score.

Only a complete valid confirmation can be eligible for independent replication.
No V4 command automatically promotes a workflow. A failed or inconclusive result
retains the prior workflow.

## Accounting and interruption

The ledger records a reservation before each physical provider call, serializes
access with a process lock, and caches completed responses by exact request and
configuration. Completed responses can be reused after interruption. Uncertain
in-flight calls fail closed in the default configuration. A model producing a
wrong program does not receive infrastructure retries.

Limits are 242 physical calls in total, including at most 48 development calls,
160 confirmation calls, 24 preparation calls, 2 preflight calls and 8 transport
retries. The pilot does not consume unused confirmation/preparation allowances.
The token accounting threshold is 3 million and elapsed run allowance 6 hours.
The existing subscription transport does not enforce a hard per-call token
ceiling: a 40,000-token reservation is a conservative accounting provision,
not a guarantee on model output or billing. Unknown usage and monetary cost
remain explicitly unknown. Record human validator preparation separately.

Program limits retain V3 CPU/time/memory settings: 6 CPU seconds and 8 wall
seconds per case, 180 wall seconds per suite and 512 MiB address space. V4
explicitly raises the output cap to 4 MiB for both policies: abc392_c permits
300,000 output integers, whose valid output can exceed the old 1 MiB cap. This
pre-registration amendment prevents evaluator-induced false failures. Historical
V3 code, results and limits remain unchanged. The validated public boundary now
uses the full 300,000-element contract. Model transport
has a separate 600-second timeout. Model tools are forbidden and detected tool
activity invalidates a response.

Evidence is stored under `.ascendra/method-search-lcb-v4-pilot/`. Checked records
and source hashes detect ordinary changes; local checksums are not an externally
signed attestation against an attacker able to rewrite the full evidence store.
