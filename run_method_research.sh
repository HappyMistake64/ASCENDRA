#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -v
python3 -m ascendra.method_research prepare
python3 -m ascendra.method_research run
python3 -m unittest discover -v
python3 -m ascendra.method_research verify
