# Workflow research V2: reviewed unique-output contracts

V1 was stopped and invalidated after a public-contract audit found that AtCoder
abc396_e permits any minimum-sum XOR assignment but the source LiveCodeBench
checker compares to one exact stored output. A synthetic fixture demonstrates
that it rejects another valid solution. No private values were inspected, no
outcomes were relabeled, and the original evidence is preserved with its costs.
The diagnostic tells us the scores are unreliable; it does not establish which
of the generated solutions were correct.

V2 excludes ALL 18 tasks registered in V1, including those not yet executed. A
conservative allowlist was reviewed from the remaining public output contracts:
31 tasks with uniquely specified integer results, counts, modular sums,
deterministic strings/matrices, or decision labels. Constructive outputs,
floating tolerance, case-insensitive outputs, and generic output descriptions
not further reviewed are excluded. METHOD_ELIGIBILITY.json records this review.
Task order is SHA256('ASCENDRA-method-search-lcb-v2:' + ID). For each difficulty,
first 3 tasks are development and next 6 confirmation: 6+12 disjoint tasks.
Selection does not depend on the private cases or model scores of these tasks.

The pinned dataset is livecodebench/code_generation_lite revision
0fe84c3912ea0c4d4a78037083943e8f0c4dd505, file test6.jsonl, SHA256
bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5.
Its public card labels the license 'cc' without a subtype; the loader's MIT
header does not establish licensing for all contest content. Preserve source
attribution. This is a local subset experiment, not an official leaderboard.

The rest of V1's protocol is retained as a new, frozen configuration:
- Requested gpt-6-astra, reasoning low, codex_subscription, two workers.
- Exactly 2 calls/trial: best_of_two, public_repair, plan_then_code, critical_review.
- Public examples select a program; most passing cases wins, ties select second.
- 6 dev tasks x 4 methods x 1 replicate = 48 calls.
- Freeze the nonbaseline method with most fully solved dev tasks, then public
  passes, then the stated method order. Compare even if it is below baseline.
- 12 disjoint confirmation tasks x 2 methods x 3 replicates = 144 calls.
- Gate: pass-rate delta >=5 percentage points, no aggregate task regression,
  one-sided task sign p<=0.05, paired Wilson lower bound >0.5.
- Complete original private suites, short-circuiting only after a failed case.
  Each candidate gets stdin and its own code in a fresh networkless sandbox;
  expected values and other cases are never mounted. Limits: 512 MiB memory,
  6s CPU/8s wall per case, 180s per suite, 1 MiB output. Public cases must pass too.
- Provider sees no private tests or private feedback. Complete requests,
  responses, selected code, scores, tokens, and fingerprints are archived.
- Stop on provider, integrity or harness error. No outcome-based retry,
  replacement or editing of scores. Interrupted calls are not repeated.

The runner is a separately frozen source snapshot, method_research_v2.py, to
preserve V1 exactly. Controller simulation tests and new eligibility tests run
before and after the study. Synthetic fixture results are not model evidence.

Limitations: public 2025 problems may be in training; few independent tasks;
same calls do not imply same tokens; Python-only custom runner; no reference
solutions supplied; no model weight update or original-lineage promotion.
Run ./run_method_research_v2.sh in a fresh workspace for a new replication.
