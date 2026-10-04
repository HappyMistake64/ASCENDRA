#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info >= (3, 11), "ASCENDRA requires Python 3.11 or newer"'
if ! command -v bwrap >/dev/null; then
  echo 'Install bubblewrap and Python venv support first: sudo apt-get install bubblewrap python3-venv' >&2
  exit 1
fi
bwrap --die-with-parent --unshare-all --ro-bind /usr /usr --symlink usr/bin /bin \
  --symlink usr/lib /lib --symlink usr/lib64 /lib64 --proc /proc --dev /dev \
  --tmpfs /tmp -- /usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 11)'
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/ascendra --help >/dev/null
.venv/bin/ascendra-agent --help >/dev/null
echo 'Installed. Activate with: source .venv/bin/activate'
echo 'Offline checks: python -m unittest discover -s tests -v'
echo 'Live runs use the official Codex CLI login; see CAPABILITY_AGENT.md.'
