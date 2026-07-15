"""Pre-registered FX signal survey CLI (#376, batch #375).

*** THE CORE DISCIPLINE OF THIS PACKAGE: NO FULL-HISTORY EXECUTION. ***

Without ``--smoke``, ``main()`` exits ``SystemExit("BLOCKED: ...")`` BEFORE
any data access -- there is no full-history code path reachable from
``main()`` in this package (that is stage 2c). ``--smoke`` runs the ENTIRE
survey composition (all 33 pre-registered cells x the full cost/tax matrix,
all 4 dumb baselines, the SPY bar, and the §6 survivor/family/class-kill
evaluator) on a code-generated deterministic SYNTHETIC fixture
(``fx_survey.make_smoke_fixture``/``make_smoke_spy_fixture``) -- never real
EUR/USD or SPY history, and never touches the gitignored FXCM cache. This
is mechanically enforced (``tests/test_run_fx_survey.py`` monkeypatches
``fx_data.read_cache``/``get_week_bytes`` to raise, for both the no-flag
and ``--smoke`` paths) and is the reviewer-checked discipline this whole
package exists to protect: violating it (running against real cache data,
even "just to check it works") destroys the pre-registration blindness the
frozen spec depends on.

Spec: ``docs/research/2026-07-13-forex-4h-strategy-preregistration.md``
(frozen SHA e409bf8). Research-only. Lives in ``backtest/`` and is never
imported by ``supabase/functions/``. No LLM, no broker calls, no orders.

Usage
-----
    venv/bin/python -m backtest.run_fx_survey             # BLOCKED (by design)
    venv/bin/python -m backtest.run_fx_survey --smoke      # synthetic-only smoke run
    venv/bin/python -m backtest.run_fx_survey --smoke --json out.json
"""
from __future__ import annotations

import argparse
import json
from typing import Optional

import numpy as np
import pandas as pd

from backtest import fx_survey

_BLOCKED_MESSAGE = (
    "BLOCKED: full-history survey execution is stage 2c; this package runs "
    "--smoke only. Re-run with --smoke to execute the full composition on a "
    "code-generated synthetic fixture (never real cache data)."
)


def _json_default(obj):
    """``json.dump(..., default=...)`` seam for the non-JSON-native types
    that appear in the smoke digest (pandas Timestamps, numpy scalars,
    NaN handled natively by the json module)."""
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    raise TypeError(f"object of type {type(obj)!r} is not JSON serializable")


def _print_banner() -> None:
    print("=" * 96)
    print("*** SYNTHETIC SMOKE RUN -- code-generated fixture, NOT real EUR/USD/SPY history. ***")
    print("*** This output reveals NOTHING about real EUR/USD price behavior. ***")
    print("Spec: docs/research/2026-07-13-forex-4h-strategy-preregistration.md (freeze SHA e409bf8)")
    print("=" * 96)


def _print_digest(result: dict) -> None:
    print(
        f"\nSaturday-UTC rows dropped (carve-out exercised): {result['n_saturday_dropped']}"
    )
    print(f"4h bars after carve-out + resample + drop-in-progress: {result['bars_4h_len']}")
    print(f"Measured (synthetic) spread reconciliation: {result['measured_spread_pips']:.3f} pips")
    print(f"Windows generated: {len(result['windows'])}")
    print(f"SPY bar median-window after-tax Calmar: {result['spy_median_calmar']!r}")

    n_cells = len(result["survivor_results"])
    n_survivors = sum(1 for r in result["survivor_results"].values() if r["is_survivor"])
    print(f"\nCandidate cells evaluated: {n_cells} (of the frozen 33 -- always all reported)")
    print(f"Survivors (synthetic data -- not a real finding): {n_survivors}")
    for family, dead in result["family_kills"].items():
        print(f"  Family {family}: {'DEAD (no survivor)' if dead else 'alive (>=1 survivor)'}")
    print(f"Class kill: {result['class_kill']}")


def main(argv: "Optional[list]" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.run_fx_survey",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="run the full composition on a synthetic fixture (the ONLY executable path)",
    )
    parser.add_argument(
        "--json", default=None, metavar="PATH",
        help="dump the smoke digest as JSON to PATH (smoke mode only)",
    )
    parser.add_argument("--seed", type=int, default=42, help="synthetic-fixture seed (default 42)")
    args = parser.parse_args(argv)

    if not args.smoke:
        raise SystemExit(_BLOCKED_MESSAGE)

    _print_banner()
    result = fx_survey.run_smoke_survey(seed=args.seed)
    _print_digest(result)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, default=_json_default, indent=2)
        print(f"\nJSON digest written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
