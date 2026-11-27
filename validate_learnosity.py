#!/usr/bin/env python3
"""Check a Learnosity item file produced by latex2quiz before uploading it.

Usage: python3 validate_learnosity.py bank.json [--fixture WISEflow-export.json]

With --fixture, the key sets of the file are also compared with a WISEflow
item export at every nesting level, and the differences are listed. Those
are informational; the exit status reflects only the validation checks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from latex2quiz_lib.learnosity import compare_keys, validate_bank


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bank", type=Path, help="Learnosity .json file to check")
    parser.add_argument("--fixture", type=Path, help="WISEflow item export to compare key sets with")
    args = parser.parse_args(argv)
    try:
        bank = json.loads(args.bank.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"error: cannot read {args.bank}: {error}", file=sys.stderr)
        return 2
    problems = validate_bank(bank)
    for problem in problems:
        print(f"problem: {problem}")
    if args.fixture:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        for path, kind, key in compare_keys(bank, fixture):
            print(f"keys: {kind:7} {path or '<root>'}: {key}")
    items = len(bank.get("data", [])) if isinstance(bank, dict) else 0
    print(f"{'FAILED' if problems else 'OK'}: {items} items, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
