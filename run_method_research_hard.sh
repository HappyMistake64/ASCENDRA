#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m ascendra.method_research_hard verify
python3 -m ascendra.method_research_hard run
