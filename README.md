# ASCENDRA

[![CI](https://github.com/HappyMistake64/ASCENDRA/actions/workflows/ci.yml/badge.svg)](https://github.com/HappyMistake64/ASCENDRA/actions/workflows/ci.yml)

ASCENDRA is an experimental Python agent that selects tools, remembers outcomes, proposes reusable capabilities, and maintains a persistent plan of ambitions. Its autonomous supervisor can choose subtasks and the number of concurrent workers within a run budget. Capabilities become callable only after independent contract verification. User goals, tool permissions and execution budgets remain authoritative.

Learning uses experience and reusable workflows; model weights do not change. The original controlled evolution and benchmark research modules remain available alongside the agent.

## Install

Linux, system Python 3.11+ and a working bubblewrap sandbox are required. Ubuntu 24.04 is the CI reference environment.

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap python3-venv
bash scripts/setup.sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Current sources are committed directly. `bootstrap_cloud.py` is a compatibility check and never extracts the old transport archive over current code.

## Run the agent

Real agent runs require the official Codex CLI installed and authenticated with subscription access to the requested model. No separately billed API key is required. The default requested model is `gpt-6-astra`, reasoning effort `low`.

```bash
codex login --device-auth
ascendra-agent demo --output /tmp/ascendra-agent-demo
```

The agent demo makes real model calls, creates two isolated example projects, independently checks the repairs, verifies a proposed workflow and tests its reuse. Use a new output directory for every demo.

To work on your project:

```bash
ascendra-agent grow \
  --project /absolute/path/to/project \
  --memory /absolute/path/to/ascendra-memory \
  --goal 'Inspect this project and improve its reliability.' \
  --allow-write src/calculator.py \
  --cycles 2

ascendra-agent status --memory /absolute/path/to/ascendra-memory
```

Memory must be outside the inspected project. Only exact paths supplied with `--allow-write` can be changed. Without `--goal`, the agent chooses a next objective from its mission, ambition plan and recorded experience. Ambitions are enabled by default; `--no-ambition` disables them for a run. A generic project goal remains unverified unless the application provides a trusted evaluator.

To let a supervisor choose work and delegate to concurrent agents:

```bash
ascendra-agent autonomous \
  --project /absolute/path/to/project \
  --output /absolute/path/to/new-autonomous-run \
  --mission 'Find and investigate useful improvements to this project.' \
  --max-agents 4 --max-calls 60 --minutes 30 \
  --allow-write src/calculator.py

# From another workspace terminal:
ascendra-agent watch --output /absolute/path/to/new-autonomous-run
ascendra-agent stop --output /absolute/path/to/new-autonomous-run
```

Each worker edits its own filtered copy. Workers share an experience journal, so later decisions can reuse independently verified workflows. Results and diffs are retained for review; they are not automatically merged into the original project. The supervisor chooses the team size up to the configured maximum and can finish early. This is software autonomy, not evidence of consciousness or free will. `watch` is a terminal command; it does not open a terminal inside ChatGPT.

## What is implemented

- Five project tools: list, read, search, isolated unittest execution, and allowlisted atomic writes.
- Persistent experience with distinct execution outcomes, objective outcomes and capability evaluations.
- Model-proposed parameterized workflows, independently checked on evaluator-owned fixtures before reuse.
- Three ambition horizons: now, next and stretch; progress uses evidence assigned to each milestone.
- Smaller diagnostic steps after failures, bounded attempts and explicit waiting when evidence is missing.
- Durable accounting for model calls and reported tokens. Unknown costs are not treated as zero.
- Concurrent workers, model-selected delegation, durable run status and a stop control.

## Evidence and limits

The latest local live demonstration used 15 model calls and 196,647 reported tokens. Both repairs passed five independent checks; an inspection workflow passed three fixture variants and was reused in the second project. Two ambition metrics were met; the broader repair-generalization ambition remains unverified. These small related projects demonstrate the complete mechanism, not general self-improvement or a measured increase in intelligence.

GitHub CI runs the complete current offline suite, including process concurrency, cancellation and publishing checks. It does not make model calls or need model credentials. Actual experiment evidence remains in the execution workspace; the repository contains source, tests and public methodological documentation.

The original `ascendra demo` command is synthetic. `ascendra-agent demo` is the real subscription-backed agent demonstration; neither should be confused with a fresh controlled confirmation study.

## Documentation

- [Agent, learning and ambitions](CAPABILITY_AGENT.md)
- [GitHub settings and environment setup](GITHUB_SETUP.md)
- [Subscription provider](SUBSCRIPTION_RUN.md)
- [Controlled research protocol](RESEARCH_PROTOCOL.md)
- [Codex Cloud experiment task](CODEX_CLOUD_TASK.md)
- [V4 development study](METHOD_RESEARCH_V4.md)
- [Hard-task development study](METHOD_RESEARCH_HARD.md)

Historical research verdicts and promotion gates are unchanged. A claim of improvement requires the corresponding registered experiment and independent evidence.
