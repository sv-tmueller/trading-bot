"""CLI for the nightly reflection engine (#578). See ``backtest/reflection.py`` module
docstring for the frozen input/output contract this thin wrapper implements.

    PYTHONPATH=. venv/bin/python backtest/run_nightly_reflection.py \\
        --date=YYYY-MM-DD \\
        --digest=digest.json \\
        --bars=bars5.csv \\
        --ledger=docs/trading-journal/daily-verification.jsonl

``PYTHONPATH=.`` (run from the repo root) is the same convention every other ``backtest/run_*.py``
script in this repo uses when invoked by file path rather than ``python -m`` (see
``docs/research/2026-06-06-regime-vs-spy-longrun-backtest.md``'s ``run_longrun.py`` invocation).

Prints one line of JSON (``{date, markdown, reflection}``) to stdout. [CORRECTED, round-1
reviewer should-fix finding 2] Exit 0 once the CLI's own arguments parse and the ``--digest``/
``--ledger`` JSON files parse; exit 1 (nothing printed) only on a malformed CLI argument or a
malformed ``--digest``/``--ledger`` JSON file. A malformed ``--bars`` CSV is NOT a CLI-boundary
failure -- it degrades into the printed envelope exactly like any other reflection-computation
failure (see ``backtest.reflection.compute_reflection``), because ``load_local`` runs inside that
function's own try/except, not at this CLI's argument-parsing boundary.
"""
from __future__ import annotations

import argparse
import json
import sys

from backtest.reflection import compute_reflection, load_ledger_jsonl


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--ledger", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit:
        # argparse already wrote usage to stderr; keep the exit-1/no-stdout contract explicit.
        return 1

    try:
        with open(args.digest, "r", encoding="utf-8") as f:
            digest = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"malformed --digest: {exc}", file=sys.stderr)
        return 1

    try:
        with open(args.ledger, "r", encoding="utf-8") as f:
            ledger_text = f.read()
        ledger_rows = load_ledger_jsonl(ledger_text)
    except (OSError, ValueError) as exc:
        print(f"malformed --ledger: {exc}", file=sys.stderr)
        return 1

    envelope = compute_reflection(args.date, digest, args.bars, ledger_rows)
    print(json.dumps(envelope))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
