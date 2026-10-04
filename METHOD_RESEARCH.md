# Controlled workflow search on LiveCodeBench

This is a separate, explicitly changed experimental configuration authorized after
the original frozen-prompt experiments. It does not mutate or promote the original
G0→G1 lineage and does not train model weights.

Pinned dataset: `livecodebench/code_generation_lite`, revision
`0fe84c3912ea0c4d4a78037083943e8f0c4dd505`, file `test6.jsonl`.
SHA256: `bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5`.
Source: https://huggingface.co/datasets/livecodebench/code_generation_lite
Its dataset card labels the license `cc` without a precise subtype; upstream
problem ownership remains with the contest sources. Preserve attribution and
source pointers; do not assume the upstream loader's MIT header licenses all
problem content. This local study is not an official leaderboard submission.

The first 9 medium and first 9 hard AtCoder stdin tasks, ordered by a fixed
SHA256(seed + ':' + ID), are split into 3+3 development and 6+6 confirmation
problems. No outcomes or private testcase contents select tasks. Problem dates
are January–April 2025; they are publicly accessible and may be in model training.

Four methods receive exactly two calls per trial to requested model
`gpt-6-astra`, reasoning `low`, via the ChatGPT subscription transport:

1. `best_of_two`: two independent programs, select by public examples.
2. `public_repair`: a program, then improvement with public execution feedback.
3. `plan_then_code`: a written algorithm plan, then a complete program.
4. `critical_review`: a program, then critical review and corrected program.

Public selection uses the number of passing public examples; ties select the
second program. Planning has only one program. The strongest nonbaseline method
on the 6 development tasks is frozen before confirmation; even if it is worse
than baseline, it is still compared honestly. Confirmation compares it to
`best_of_two` on 12 disjoint problems with 3 paired replicates. Methods rotate
order; concurrency is exactly two trials. Total: 192 experimental calls and one
provider preflight. Equal calls are not equal tokens or exact compute.

The confirmation gate requires ≥5 percentage points improvement, no per-task
aggregate regression, task-cluster one-sided sign p≤0.05, and paired Wilson
lower bound >0.5. Development scores cannot establish a confirmed gain.

The private grader uses the complete source test collection, short-circuiting
on the first failure because the endpoint is all-cases correctness. Each case
gets a fresh networkless bubblewrap sandbox, only a program and resource wrapper,
stdin, 512 MiB memory, 6 seconds CPU / 8 seconds wall, 1 MiB output limit.
The entire suite has a 180-second wall limit. Expected outputs and other cases
are never mounted into the program. The exact line/Decimal output comparator
matches the pinned LiveCodeBench framework at commit
`28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`. Public examples also must all pass.
No private input, expected value, traceback, or failing case is sent to a model.
The dataset has no canonical reference solutions; independent synthetic fixtures
validate the harness and are not counted as research evidence.

Every request, response, selected program, public selection, private pass/fail,
provider token record, source fingerprint and winner freeze is archived under
`.ascendra/method-search-lcb-v1/`. Never publish credentials. Preserve all failures;
never replace tasks or repeat a failed call to obtain a better response. A
partial in-flight response without an archived result blocks resumption.

Run `./run_method_research.sh`. Preregistration is created before real calls;
post-registration source changes invalidate the study.
