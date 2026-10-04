#!/usr/bin/env python3
"""Compatibility check: current sources are checked in, never restore old code."""
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    required = ('pyproject.toml', 'ascendra/cli.py', 'ascendra/capability_cli.py',
                'ascendra/capability_ambition.py', 'tests/test_capability_ambition_integration.py')
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise SystemExit('Incomplete source checkout: ' + ', '.join(missing)
                         + '. Restore the current Git revision; the historical archive is not used.')
    print('Current ASCENDRA sources are present. Run bash scripts/setup.sh; no archive was extracted.')


if __name__ == '__main__':
    main()
