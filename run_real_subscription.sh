#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Authentication is supplied by `codex login --device-auth`; no API key is used.
python3 -m unittest discover -v
# evolve performs the real provider/isolation preflight before archiving evidence.
status=0
python3 -m ascendra.cli evolve \
  --provider codex_subscription --benchmark real_v1 \
  --model gpt-6-astra --effort low --generations 2 --replicates 3 --fresh || status=$?
python3 -m ascendra.cli export
python3 -m ascendra.cli status > .ascendra/status.json
printf '%s\n' 'Detailed status saved to .ascendra/status.json (evaluator-only output).'
python3 -m unittest discover -v
exit "$status"
