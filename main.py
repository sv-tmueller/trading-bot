"""CLI entry point — ad-hoc backtests of the regime strategy.

The production bot is now the TypeScript app under ``supabase/`` (Supabase Edge
Functions + Alpaca; see ``docs/``). This module only wraps
``backtest/regime.py`` for offline research. The old IBKR/SQLite operator
commands (``panic``, ``summary``) were removed when that bot was decommissioned
(#232) — incident response now lives in the token-authed ``panic`` Edge Function.
"""
from __future__ import annotations

import sys


def _run_backtest(argv: list[str]) -> int:
    """Forward args to ``backtest/regime.py::main_cli`` via ``sys.argv``."""
    from backtest.regime import main_cli

    saved_argv = sys.argv
    try:
        sys.argv = ["backtest/regime.py", *argv]
        main_cli()
    finally:
        sys.argv = saved_argv
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher. Returns a Unix exit code (0 = success)."""
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv else None

    if mode == "backtest":
        return _run_backtest(argv[1:])

    print("Usage: python main.py backtest [--years N] [--vehicle UPRO] [--benchmark SPY] [--sma 200]")
    return 0 if mode is None else 2


if __name__ == "__main__":
    sys.exit(main())
