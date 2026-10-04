#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m ascendra.method_research_v4 verify
python3 -m ascendra.method_research_v4 run
