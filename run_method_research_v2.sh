#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -v
python3 -m ascendra.method_research_v2 prepare
python3 -m ascendra.method_research_v2 run
python3 -m unittest discover -v
python3 -m ascendra.method_research_v2 verify
