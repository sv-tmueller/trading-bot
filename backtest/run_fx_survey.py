"""Pre-registered FX signal survey CLI (#376, batch #375; --full: #379, batch #378).

Two mutually exclusive executable paths, both gated behind an explicit
flag -- without ``--smoke`` or ``--full``, ``main()`` exits
``SystemExit("BLOCKED: ...")`` BEFORE any data access:

- ``--smoke`` runs the ENTIRE survey composition (all 33 pre-registered
  cells x the full cost/tax matrix, 3 simulated dumb baselines +
  always-flat applied as the median-return>0 criterion, the SPY bar, and
  the §6 survivor/family/class-kill evaluator) on a code-generated
  deterministic SYNTHETIC fixture (``fx_survey.make_smoke_fixture``/
  ``make_smoke_spy_fixture``) -- never real EUR/USD or SPY history, and
  never touches the gitignored FXCM cache. This is mechanically enforced
  (``tests/test_run_fx_survey.py`` monkeypatches ``fx_data.read_cache``/
  ``get_week_bytes`` to raise, for both the no-flag and ``--smoke`` paths)
  and is the reviewer-checked discipline PR #376/#377 exist to protect:
  violating it (running against real cache data, even "just to check it
  works") destroys the pre-registration blindness the frozen spec depends
  on.
- ``--full`` (stage 2c, #379) executes the SAME composition against the
  REAL, pinned FXCM cache (``prepare_history(fetch=False, ...)`` --
  ``fetch`` is never exposed as a flag; refreshing the cache is out of
  scope, see SUB_PLAN §4) and REAL SPY history (``spy_fetch=None`` routes
  ``run_survey`` to the real ``fx_survey._fetch_spy`` yfinance seam --
  needs ``REQUESTS_CA_BUNDLE`` set in some sandboxes). Requires
  ``--spread-pips`` (the measured FXCM spread reconciliation input --
  an explicit, visible CLI argument rather than a buried constant, so it
  can't drift silently and always appears in the repro command). ONE-RUN
  DISCIPLINE (SUB_PLAN §5): exactly one scoring execution of this path is
  authorized per pre-registration; see
  ``docs/research/2026-07-15-forex-4h-survey-verdict.md``'s execution log.

Spec: ``docs/research/2026-07-13-forex-4h-strategy-preregistration.md``
(frozen SHA e409bf8). Research-only. Lives in ``backtest/`` and is never
imported by ``supabase/functions/``. No LLM, no broker calls, no orders.

Usage
-----
    venv/bin/python -m backtest.run_fx_survey             # BLOCKED (by design)
    venv/bin/python -m backtest.run_fx_survey --smoke      # synthetic-only smoke run
    venv/bin/python -m backtest.run_fx_survey --smoke --json out.json
    venv/bin/python -m backtest.run_fx_survey --full --spread-pips 0.20 \
        --end-year 2026 --json data/fx_survey/2026-07-15-full-run.json
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Optional

import numpy as np
import pandas as pd

from backtest import fx_survey

_BLOCKED_MESSAGE = (
    "BLOCKED: full-history survey execution is stage 2c; this package runs "
    "--smoke only. Re-run with --smoke to execute the full composition on a "
    "code-generated synthetic fixture (never real cache data)."
)

# ND-A (lead decision, batch #378, Interpretation 2): the data-kill gate
# deterministically BLOCKs on the pinned real FXCM cache with exactly these
# three reasons, all pre-adjudicated (investigated BLIND, before any
# strategy result) in the merged #374 note
# (docs/research/2026-07-13-fx-4h-harness-plumbing-check.md §4/§5). The
# exact-string pin doubles as a cache-integrity check: a drifted/refreshed
# cache changes the percentages and re-BLOCKs on an unmatched reason.
ADJUDICATED_CROSSINGS = (
    (2024, "missing weeks 7.55% > 2.00%"),
    (2025, "missing weeks 7.55% > 2.00%"),
    ("all", "crossed-quotes rate 2.3791% > 0.100%"),
)


def _json_default(obj):
    """``json.dump(..., default=...)`` seam for the non-JSON-native types
    that appear in the digest (pandas Timestamps, numpy scalars, NaN
    handled natively by the json module)."""
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


def _print_full_banner(*, spread_pips: float, end_year: int, cache_span: str) -> None:
    print("=" * 96)
    print("*** FULL-HISTORY SURVEY RUN -- REAL FXCM EUR/USD cache + REAL SPY history (yfinance). ***")
    print("*** This is THE ONE RUN (SUB_PLAN Sec5 one-run discipline) -- see the verdict doc. ***")
    print("Spec: docs/research/2026-07-13-forex-4h-strategy-preregistration.md (freeze SHA e409bf8)")
    print(f"Spread input (--spread-pips, measured FXCM spread reconciliation): {spread_pips:.3f} pips")
    print(f"End year: {end_year} (2026 generated as unscored coverage per ND1, not fed into any survivor statistic)")
    print(f"Cache span (post-carve-out 4h bars): {cache_span}")
    print("=" * 96)


def _print_full_digest(result: dict) -> None:
    print(f"\nRaw H1 history rows (pre-carve-out): {result['history_rows']}")
    print(f"Duplicate H1 timestamps: {result['n_duplicates']}")
    print(f"Saturday-UTC rows dropped (carve-out exercised): {result['n_saturday_dropped']}")
    print(f"4h bars after carve-out + resample + drop-in-progress: {result['bars_4h_len']}")

    adjudicated = result["adjudicated_crossings"]
    print(f"Adjudicated data-kill crossings (pre-investigated, #374 note): {len(adjudicated)}")
    for label, reason in adjudicated:
        print(f"  {label}: {reason}")

    print(f"Measured spread reconciliation input: {result['measured_spread_pips']:.3f} pips")
    print(f"Windows generated: {len(result['windows'])}")
    print(f"SPY bar median-window after-tax Calmar: {result['spy_median_calmar']!r}")

    n_cells = len(result["survivor_results"])
    n_survivors = sum(1 for r in result["survivor_results"].values() if r["is_survivor"])
    print(f"\nCandidate cells evaluated: {n_cells} (of the frozen 33 -- always all reported)")
    print(f"Survivors: {n_survivors}")
    for family, dead in result["family_kills"].items():
        print(f"  Family {family}: {'DEAD (no survivor)' if dead else 'alive (>=1 survivor)'}")
    print(f"Class kill: {result['class_kill']}")


def _run_full(args: argparse.Namespace) -> int:
    """The stage 2c interface (SUB_PLAN pre-flight facts): ``prepare_history``
    -> ``slice_calendar_year_windows`` -> ``run_survey``. ``fetch=False``
    always (no refresh flag exposed -- pinned cache); ``spy_fetch=None``
    routes ``run_survey`` to the real ``fx_survey._fetch_spy`` yfinance
    seam. Provenance keys from ``prepare_history`` are merged into the
    ``run_survey`` digest so a single JSON artifact carries both."""
    prep = fx_survey.prepare_history(
        fetch=False, end_year=args.end_year, adjudicated_reasons=ADJUDICATED_CROSSINGS,
    )
    bars_4h = prep["bars_4h"]
    windows = fx_survey.slice_calendar_year_windows(bars_4h.index)
    result = fx_survey.run_survey(
        bars_4h, windows, measured_spread_pips=args.spread_pips, spy_fetch=None,
    )

    result["n_saturday_dropped"] = prep["n_saturday_dropped"]
    result["bars_4h_len"] = len(bars_4h)
    result["resample_report"] = prep["resample_report"]
    result["completeness"] = prep["completeness"]
    result["history_rows"] = prep["history_rows"]
    result["n_duplicates"] = prep["n_duplicates"]
    result["adjudicated_crossings"] = prep["adjudicated_crossings"]

    cache_span = f"{bars_4h.index[0]} -> {bars_4h.index[-1]}" if len(bars_4h) else "n/a"
    _print_full_banner(spread_pips=args.spread_pips, end_year=args.end_year, cache_span=cache_span)
    _print_full_digest(result)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, default=_json_default, indent=2)
        print(f"\nJSON digest written to {args.json}")

    return 0


def main(argv: "Optional[list]" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.run_fx_survey",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--smoke", action="store_true",
        help="run the full composition on a synthetic fixture (never real cache data)",
    )
    mode_group.add_argument(
        "--full", action="store_true",
        help=(
            "run the full composition against the REAL FXCM cache + real SPY "
            "history (yfinance). Requires --spread-pips. ONE-RUN DISCIPLINE applies."
        ),
    )
    parser.add_argument(
        "--json", default=None, metavar="PATH",
        help="dump the digest as JSON to PATH (smoke or full mode)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="synthetic-fixture seed (default 42, --smoke only)",
    )
    parser.add_argument(
        "--spread-pips", type=float, default=None, metavar="PIPS",
        help=(
            "measured FXCM spread reconciliation input, in pips -- REQUIRED with "
            "--full, rejected with --smoke"
        ),
    )
    parser.add_argument(
        "--end-year", type=int, default=2026,
        help="last calendar year to load from the cache (--full only; default 2026)",
    )
    args = parser.parse_args(argv)

    if not args.smoke and not args.full:
        raise SystemExit(_BLOCKED_MESSAGE)

    if args.smoke:
        if args.spread_pips is not None:
            parser.error("--spread-pips is only valid with --full")
        _print_banner()
        result = fx_survey.run_smoke_survey(seed=args.seed)
        _print_digest(result)
        if args.json:
            with open(args.json, "w") as fh:
                json.dump(result, fh, default=_json_default, indent=2)
            print(f"\nJSON digest written to {args.json}")
        return 0

    # --full
    if args.spread_pips is None:
        parser.error("--spread-pips is required with --full")
    if not math.isfinite(args.spread_pips) or args.spread_pips <= 0:
        parser.error("--spread-pips must be a finite number > 0")
    return _run_full(args)


if __name__ == "__main__":
    raise SystemExit(main())
