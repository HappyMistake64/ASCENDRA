# ASCENDRA Research Protocol v0.3

## Question
Can an accepted software-engineering strategy cause creation of a successor that performs better on unseen tasks under controlled conditions, and can the accepted successor repeat the gain on a fresh holdout?

## Experimental unit
Strategy prompt + pinned provider/model + pinned reasoning effort + benchmark version + resource policy.

## Generation protocol
1. Select the generation-specific holdout (H1, then H2, rotating thereafter).
2. Evaluate the current champion from clean task workspaces.
3. Mutate the strategy using evaluator-confirmed failure evidence only.
4. Evaluate the candidate on the identical task set and constraints.
5. Repeat the paired evaluation N times (default N=3 for real runs).
6. Aggregate paired outcomes and per-task solve counts.
7. Emit `IMPROVED`, `INCONCLUSIVE`, or `REGRESSED`.
8. Promote only `IMPROVED`; otherwise restore/retain the prior champion.

## Leakage controls
- Private evaluator files live under `.ascendra_hidden/**`.
- Provider snapshots exclude private files.
- Model writes to private paths are rejected.
- Codex receives serialized public source, not evaluator workspace paths.
- Each task evaluation starts from a clean copied workspace.

## Statistics
ASCENDRA records paired gains/losses/ties on holdout outcomes and a Wilson 95% interval for the candidate win fraction among discordant pairs. Any aggregate task regression blocks promotion. Small samples remain explicitly `INCONCLUSIVE` rather than being presented as evidence.

## Recursion criterion
Minimum exploratory recursive result:
- G0 causes G1.
- G1 is `IMPROVED` against G0 on H1 and promoted.
- G1 causes G2.
- G2 is `IMPROVED` against G1 on fresh H2 and promoted.

## Resource evidence
Codex runs use JSONL event mode. ASCENDRA records model calls and reported input/output tokens when available. Estimated monetary cost remains zero until a versioned pricing source is configured; unknown cost is never fabricated.

## Claim discipline
`real_v1` is a controlled local benchmark, not sufficient for a scientific claim of general recursive self-improvement. Strong claims require larger external repositories, more task families, independent replication, environment/model pinning, resource normalization, and held-out data never exposed to the mutation process.
