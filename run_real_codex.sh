#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m ascendra.cli doctor
python3 -m ascendra.cli evolve \
  --provider codex_cli \
  --benchmark real_v1 \
  --model gpt-6-astra \
  --effort low \
  --generations 2 \
  --replicates 3 \
  --fresh
python3 -m ascendra.cli export
python3 -m ascendra.cli status
