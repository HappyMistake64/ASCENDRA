#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -v
python3 -m ascendra.external_research prepare
status=0
python3 -m ascendra.external_research run || status=$?
python3 -m unittest discover -v
exit "$status"
