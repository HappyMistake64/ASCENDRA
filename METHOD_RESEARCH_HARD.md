# Hard development pilot after the V4 ceiling

The first V4 pilot solved all 12 tasks with both strategies. It used 37 physical
subscription calls including preflight and 368,542 reported tokens; no repair
was triggered. That outcome measures a development ceiling, not a quality gain.
The user requested a substantial increase in difficulty. This new study keeps
that evidence frozen and prepares a separate 12-task hard development pilot.

## What becomes harder

All tasks carry the pinned dataset's `hard` label. The tasks are abc392_g,
abc399_f, arc194_b, arc194_e, abc394_e, abc394_g, abc395_e, abc394_f, abc398_g,
abc397_g, abc399_e and abc390_e. They cover large arithmetic-progression counts,
modular sums, permutation sorting, constrained string operations, palindromic
paths, grid bottlenecks, graph reversal costs, tree structure optimization,
bipartite games, adversarial shortest paths, global character replacement and
multi-resource knapsack.

The suite includes previously exposed difficult tasks and known failures. It is
explicitly DEVELOPMENT evidence. No task from the reserved fresh confirmation
pool is used and the old scores are not rewritten. A multi-output cube task was
excluded before registration because the exact checker would be invalid.

Public diagnostic builders provide public samples, independent small-instance
oracle checks and certified structured large cases. In particular, Fine Triplets
includes a near-million-element dense set with a missing middle element, which
breaks the contiguous-set shortcut. Large stress answers need an independent
closed-form certificate or small-instance validation of the formula; model
agreement is never accepted as an oracle.

## Fixed comparison

The V4 research protocol, model `gpt-6-astra`, reasoning `low`, two workflow
policies and maximum two candidate calls per policy/task remain fixed. Policy A
uses two independent proposals. Policy B requests a repair only after verified
public failure. All checks have equal weight and ties choose the first program.
The controller receives only public data. For oversized public inputs, the
hard-study feedback retains the validated case label alongside the omission
marker, input length and hash; it never supplies a truncated input as a complete
test. This explicit feedback amendment helps identify which public stress failed
while retaining the eight-case/20,000-character feedback cap. Selection freezes before private
grading; private outcomes cannot trigger another candidate call.

Per-program constraints remain 6 CPU seconds, 8 wall seconds per case, 180 wall
seconds per suite, 512 MiB memory and 4 MiB output. Model transport timeout is
600 seconds. Each public suite has at most 18 cases (at most 144 seconds
of case deadlines). Reproducibility rechecks are additional, individually
bounded case runs, at most another 144 seconds per candidate; they are not
extra model calls. The run is serial. Both policies use the same task checks and
limits. Actual token usage is measured, not asserted equal.

## Scope and budget

This is a new, separately registered development study. Its own development cap
is 48 candidate calls plus preflight (at most 2). No preparation LLM calls are
made by the runner. Total ledger policy retains the V4 admission caps of 242
physical calls, 3 million reported/accounted tokens and 6 hours; unused phase
allowances do not authorize extra candidate attempts. Infrastructure retry is
disabled. Earlier V4 calls are reported separately and cumulatively in delivery.
Engineering-assistant/model work is not included in experimental provider counts.

The CLI provider cannot enforce a hard output-token ceiling; 40,000-token
reservations control admission of further calls, and unknown usage stays
unknown. Monetary cost is not measured.

## Execute

```bash
python3 -m unittest discover -v
python3 -m ascendra.method_research_hard prepare
python3 -m ascendra.method_research_hard verify
./run_method_research_hard.sh
python3 -m ascendra.method_research_hard status
```

Do not edit any registered dependencies after preparation. A failed integrity
check requires a new version/registration, not an overwritten manifest. Previous
V3 and V4 sources and evidence remain unchanged.

Record per-task selected correctness, public failures, whether repair was
triggered, whether it improved diagnostics, private outcomes, model calls,
tokens, duration and infrastructure errors. Complete the fixed schedule even
if early results are unfavorable; infrastructure or validity failures stop it.

This study cannot promote the original strategy lineage or prove held-out
improvement. A fresh confirmation requires validated new task bundles, adequate
sample-size planning and a new frozen registration. Higher difficulty is a
measurement change, not evidence that the model itself has improved.
