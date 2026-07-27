"""Export golden-parity fixtures for the ``candlestick.ts`` TypeScript port (#467).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls, no network. Generates two committed JSON fixtures consumed by
the Deno golden-parity test ``supabase/functions/_shared/candlestick.golden.test.ts``:

- ``candlestick-golden-shapes.json`` -- hand-constructed shapes lifted verbatim from
  ``tests/test_candlestick.py`` (the arithmetic oracle), plus degenerate cases, warm-up
  rows and an empty case.
- ``candlestick-golden-spy.json`` -- a real-shaped 2,000-bar daily OHLC series with
  per-pattern fires/counts, firing-rate diagnostics, trend-context masks and 200-window
  SMA values, so the TS port can be checked against the SAME oracle numbers on a
  realistic (not hand-picked) frame.

SPY-data substitution -- read this before touching the SPY case
-----------------------------------------------------------------
The originating sub-plan called for the last 2,000 rows of a committed
``data/SPY_daily.csv``. That file is **not present** in this checkout: ``data/`` is
entirely gitignored (see ``.gitignore``) and the directory does not exist on disk
either. Fetching it live would (a) add a network dependency this exporter must not have
and (b) make the fixture unreproducible for anyone without that gitignored file.

Substitution taken instead, per the batch's documented fallback: ``spy_last_2000`` is a
**deterministic synthetic** 2,000-bar daily OHLC series (geometric-Brownian-motion-shaped
log returns, realistic gaps/wicks), generated with a **fixed seed** embedded below
(``SPY_FIXTURE_SEED``) using the exact same generator shape as
``tests/test_candlestick.py::_random_walk_frame`` (opens NOT pinned to the prior close).
No network, no gitignored dependency, byte-for-byte idempotent on re-export with the same
seed (see ``test_export_is_byte_identical_to_the_committed_fixture``). If a real
``data/SPY_daily.csv`` becomes available later, swapping ``_spy_like_frame`` for a real
2,000-row slice is a mechanical follow-up -- the fixture schema does not change.

Invocation
----------
``python3 -m backtest.run_candlestick_fixture_export --out supabase/functions/_shared/testdata/``
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest import candlestick as cs

SCHEMA = 1

# Frozen -- changing this changes the committed SPY fixture. Do not tune casually.
SPY_FIXTURE_SEED = 20260726
SPY_FIXTURE_BARS = 2000

CONTEXT_WINDOWS: Tuple[int, ...] = (20, 200)
CONTEXT_MODES: Tuple[str, ...] = (cs.CONTEXT_REVERSAL, cs.CONTEXT_CONTINUATION)
CONTEXT_DIRECTIONS: Tuple[str, ...] = (cs.BULLISH, cs.BEARISH)

SMA_GUARD_WINDOW = 200
#: No fixture bar may sit closer than this (relative to price) to its own rolling SMA --
#: see the module docstring's "fixture guard band" trap. If this ever fires, move the
#: slice/reseed; never loosen the bound. This guard applies to the SPY case ONLY --
#: it exists to keep an ULP-level rolling-mean difference from ever flipping a golden
#: boolean on a REAL (non-deliberate) close/SMA relationship. It is deliberately not
#: applied to CONTEXT_TIE_CASE_NAME below: an exact tie there is the point of the case
#: (both languages evaluate `10.0 == 10.0` bit-identically, so it is immune to the ULP
#: hazard by construction), and the case never carries an "sma" block, so the guard-band
#: check -- which only iterates cases with an "sma" key -- naturally never sees it.
SMA_GUARD_MIN_MARGIN = 1e-9

#: Fix round 1 (tester finding 1): a deliberate exact-tie case pinning Python's
#: `below = NOT above` context-mask semantics (candlestick.py:358-359) -- a bar with
#: close === sma is admitted into "below", not excluded from both partitions.
CONTEXT_TIE_CASE_NAME = "context_tie_constant_close"
CONTEXT_TIE_WINDOW = 3
CONTEXT_TIE_BARS = 5
CONTEXT_TIE_CLOSE = 10.0

THRESHOLDS: Dict[str, float] = {
    "DOJI_BODY_MAX": cs.DOJI_BODY_MAX,
    "HAMMER_WICK_MIN": cs.HAMMER_WICK_MIN,
    "HAMMER_OPP_WICK_MAX": cs.HAMMER_OPP_WICK_MAX,
    "PIN_WICK_MIN": cs.PIN_WICK_MIN,
    "MARUBOZU_BODY_MIN": cs.MARUBOZU_BODY_MIN,
    "STAR_BODY_MAX": cs.STAR_BODY_MAX,
    "CONTEXT_SMA_WINDOW": cs.CONTEXT_SMA_WINDOW,
    "FIRING_RATE_MAX": cs.FIRING_RATE_MAX,
    "FIRING_RATE_MIN": cs.FIRING_RATE_MIN,
}

PATTERN_ORDER: List[str] = list(cs.PATTERNS.keys())
DIRECTIONS: Dict[str, str] = {name: d for name, (_, d) in cs.PATTERNS.items()}


# ---------------------------------------------------------------------------
# Frame construction helpers
# ---------------------------------------------------------------------------

def _frame(bars: List[Tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(bars), freq="D")
    return pd.DataFrame(
        {
            "Open": [b[0] for b in bars],
            "High": [b[1] for b in bars],
            "Low": [b[2] for b in bars],
            "Close": [b[3] for b in bars],
        },
        index=idx,
    )


#: A neutral filler bar: small body, symmetric, matches no directional pattern.
#: Mirrors tests/test_candlestick.py's FILLER exactly.
FILLER: Tuple[float, float, float, float] = (100.0, 100.5, 99.5, 100.0)


def _shapes_bar_lists() -> List[Tuple[str, List[Tuple[float, float, float, float]]]]:
    """Hand-constructed frames lifted verbatim from tests/test_candlestick.py, plus
    degenerate cases, warm-up rows and an empty case. Each is a (name, bars) pair."""
    return [
        ("hammer_positive", [FILLER, (100.0, 101.2, 97.0, 101.0)]),
        ("hammer_rejects_long_upper_wick", [FILLER, (100.0, 104.0, 99.8, 101.0)]),
        ("hammer_rejects_body_too_large_for_wick", [FILLER, (100.0, 103.1, 99.0, 103.0)]),
        ("shooting_star_is_the_hammer_mirror", [FILLER, (101.0, 104.0, 100.8, 100.0)]),
        ("pin_bars_two_thirds_of_range", [FILLER, (100.0, 100.6, 97.6, 100.2)]),
        ("marubozu_dominates_range", [FILLER, (100.0, 110.0, 100.0, 109.5)]),
        ("marubozu_rejects_big_wicks", [FILLER, (100.0, 115.0, 95.0, 109.5)]),
        ("doji_small_body", [FILLER, (100.0, 102.0, 98.0, 100.05)]),
        ("doji_rejects_full_body", [FILLER, (100.0, 110.0, 100.0, 110.0)]),
        (
            "bullish_engulfing_positive",
            [FILLER, (105.0, 105.5, 99.5, 100.0), (99.0, 106.5, 98.5, 106.0)],
        ),
        (
            "bullish_engulfing_rejects_non_engulfing_body",
            [FILLER, (105.0, 105.5, 99.5, 100.0), (101.0, 106.5, 100.5, 106.0)],
        ),
        (
            "engulfing_inclusive_no_gap_bullish",
            [FILLER, (105.0, 105.5, 99.5, 100.0), (100.0, 106.5, 99.5, 106.0)],
        ),
        (
            "engulfing_inclusive_no_gap_bearish",
            [FILLER, (100.0, 105.5, 99.5, 105.0), (105.0, 105.5, 98.5, 99.0)],
        ),
        (
            "harami_vs_engulfing_bearish_prior",
            [FILLER, (110.0, 110.5, 99.5, 100.0), (102.0, 108.5, 101.5, 108.0)],
        ),
        (
            "harami_vs_engulfing_bullish_prior",
            [FILLER, (100.0, 110.5, 99.5, 110.0), (111.0, 111.5, 98.5, 99.0)],
        ),
        (
            "bullish_engulfing_requires_prior_bearish",
            [FILLER, (100.0, 105.5, 99.5, 105.0), (99.0, 106.5, 98.5, 106.0)],
        ),
        (
            "bearish_engulfing_is_the_mirror",
            [FILLER, (100.0, 105.5, 99.5, 105.0), (106.0, 106.5, 98.5, 99.0)],
        ),
        (
            "bearish_harami_positive",
            [FILLER, (100.0, 110.5, 99.5, 110.0), (108.0, 108.5, 101.5, 102.0)],
        ),
        (
            "inside_bar_full_range_containment",
            [FILLER, (100.0, 110.0, 90.0, 105.0), (101.0, 108.0, 92.0, 103.0)],
        ),
        (
            "inside_bar_rejects_poke_above",
            [FILLER, (100.0, 110.0, 90.0, 105.0), (101.0, 111.0, 92.0, 103.0)],
        ),
        (
            "morning_star_positive",
            [
                FILLER,
                (110.0, 110.5, 99.5, 100.0),
                (98.0, 99.0, 97.0, 97.5),
                (99.0, 107.5, 98.5, 107.0),
            ],
        ),
        (
            "morning_star_rejects_close_below_prior_midpoint",
            [
                FILLER,
                (110.0, 110.5, 99.5, 100.0),
                (98.0, 99.0, 97.0, 97.5),
                (99.0, 104.5, 98.5, 104.0),
            ],
        ),
        (
            "morning_star_rejects_large_middle_body",
            [
                FILLER,
                (110.0, 110.5, 99.5, 100.0),
                (98.0, 98.5, 94.0, 94.5),
                (99.0, 107.5, 98.5, 107.0),
            ],
        ),
        (
            "evening_star_positive",
            [
                FILLER,
                (100.0, 110.5, 99.5, 110.0),
                (112.0, 114.0, 111.0, 112.5),
                (111.0, 111.5, 102.5, 103.0),
            ],
        ),
        # Degenerate bars -- a zero-range bar is never a setup for any detector.
        ("degenerate_zero_range_bar", [FILLER, (100.0, 100.0, 100.0, 100.0), FILLER]),
        # A zero-body bar with a long lower wick still qualifies for hammer (the ratio
        # test is written as a product so a zero body does not divide) -- see
        # candlestick.py:122-126.
        ("degenerate_zero_body_long_lower_wick", [FILLER, (100.0, 100.0, 95.0, 100.0)]),
        # Warm-up rows: no t-1 / t-2 history -- every 2-/3-bar pattern must be False.
        ("warmup_rows_only_filler", [FILLER, FILLER, FILLER]),
    ]


def _spy_like_frame(n: int = SPY_FIXTURE_BARS, seed: int = SPY_FIXTURE_SEED) -> pd.DataFrame:
    """Deterministic synthetic daily OHLC. Same generator shape as
    tests/test_candlestick.py::_random_walk_frame (opens NOT pinned to the prior close,
    so gaps occur), just a longer, fixed-seed run. See the module docstring for why this
    replaces a real ``data/SPY_daily.csv`` slice.
    """
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, n)))
    bars: List[Tuple[float, float, float, float]] = []
    for i in range(n):
        base = close[i - 1] if i else 100.0
        o = base * (1 + rng.normal(0, 0.002))
        c = float(close[i])
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
        bars.append((float(o), float(hi), float(lo), float(c)))
    return _frame(bars)


# ---------------------------------------------------------------------------
# Per-case computation -- every value passed through float()/int()/bool() before it
# ever reaches json.dump (np.float64 / np.bool_ are not JSON-serializable and a
# ``default=`` fallback risks a lossy str()).
# ---------------------------------------------------------------------------

def _bars_json(df: pd.DataFrame) -> List[Dict[str, float]]:
    return [
        {"o": float(o), "h": float(h), "l": float(low), "c": float(c)}
        for o, h, low, c in zip(df["Open"], df["High"], df["Low"], df["Close"])
    ]


def _fires_and_counts(df: pd.DataFrame) -> Tuple[Dict[str, List[int]], Dict[str, int]]:
    fires: Dict[str, List[int]] = {}
    counts: Dict[str, int] = {}
    for name in PATTERN_ORDER:
        mask = cs.detect(name, df)
        idx = [int(i) for i in np.flatnonzero(mask.to_numpy(dtype=bool))]
        fires[name] = idx
        counts[name] = len(idx)
    return fires, counts


def _firing_rates_json(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    rates = cs.firing_rates(df)
    out: Dict[str, Dict[str, Any]] = {}
    for name in PATTERN_ORDER:
        row = rates.loc[name]
        out[name] = {
            "count": int(row["count"]),
            "rate": float(row["rate"]),
            "verdict": str(row["verdict"]),
        }
    return out


def _context_json(df: pd.DataFrame) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for window in CONTEXT_WINDOWS:
        for mode in CONTEXT_MODES:
            for direction in CONTEXT_DIRECTIONS:
                mask = cs.context_mask(df, direction, mode, window=window)
                admitted = [int(i) for i in np.flatnonzero(mask.to_numpy(dtype=bool))]
                out.append(
                    {
                        "mode": mode,
                        "direction": direction,
                        "window": int(window),
                        "admitted": admitted,
                    }
                )
    return out


def _sma_json(df: pd.DataFrame, window: int = SMA_GUARD_WINDOW) -> Dict[str, Any]:
    closes = df["Close"].astype(float)
    sma = closes.rolling(window).mean()
    valid = sma.notna()
    if valid.any():
        margin = (closes[valid] - sma[valid]).abs() / closes[valid].abs().clip(lower=1.0)
        min_margin = float(margin.min())
        if min_margin < SMA_GUARD_MIN_MARGIN:
            raise ValueError(
                f"SMA guard-band violated: |close-sma| relative margin {min_margin} < "
                f"{SMA_GUARD_MIN_MARGIN} -- move the slice or reseed, never loosen "
                "this check (see module docstring)."
            )
    else:
        min_margin = None
    values: List[Optional[float]] = [
        None if pd.isna(v) else float(v) for v in sma.to_numpy()
    ]
    return {"window": int(window), "min_margin": min_margin, "values": values}


def _build_case(name: str, df: pd.DataFrame, *, with_diagnostics: bool) -> Dict[str, Any]:
    fires, counts = _fires_and_counts(df)
    case: Dict[str, Any] = {
        "name": name,
        "bars": _bars_json(df),
        "fires": fires,
        "counts": counts,
    }
    if with_diagnostics:
        case["firing_rates"] = _firing_rates_json(df)
        case["context"] = _context_json(df)
        case["sma"] = _sma_json(df)
    return case


def _build_context_tie_case() -> Dict[str, Any]:
    """A deliberate exact-tie context case: `CONTEXT_TIE_BARS` bars, constant close
    (`CONTEXT_TIE_CLOSE`), window `CONTEXT_TIE_WINDOW`. SMA is NaN for the first
    `window - 1` bars and an EXACT tie with every close thereafter -- both languages
    evaluate `10.0 == 10.0` bit-identically, so this is immune to the ULP hazard the
    SMA guard band exists for (see SMA_GUARD_MIN_MARGIN's docstring); no "sma" block
    is emitted for this case, only "context".

    Pins Python's `below = NOT above` semantics (candlestick.py:358-359): a tie is
    admitted into "below", not excluded from both partitions.
    """
    bar = (CONTEXT_TIE_CLOSE, CONTEXT_TIE_CLOSE, CONTEXT_TIE_CLOSE, CONTEXT_TIE_CLOSE)
    df = _frame([bar] * CONTEXT_TIE_BARS)
    case = _build_case(CONTEXT_TIE_CASE_NAME, df, with_diagnostics=False)
    context: List[Dict[str, Any]] = []
    for mode in CONTEXT_MODES:
        for direction in CONTEXT_DIRECTIONS:
            mask = cs.context_mask(df, direction, mode, window=CONTEXT_TIE_WINDOW)
            admitted = [int(i) for i in np.flatnonzero(mask.to_numpy(dtype=bool))]
            context.append(
                {
                    "mode": mode,
                    "direction": direction,
                    "window": CONTEXT_TIE_WINDOW,
                    "admitted": admitted,
                }
            )
    case["context"] = context
    return case


def build_shapes_fixture() -> Dict[str, Any]:
    cases = [
        _build_case(name, _frame(bars), with_diagnostics=False)
        for name, bars in _shapes_bar_lists()
    ]
    cases.append(_build_case("empty", _frame([]), with_diagnostics=False))
    cases.append(_build_context_tie_case())
    return {
        "schema": SCHEMA,
        "source": "backtest/run_candlestick_fixture_export.py",
        "generated_from": "hand-constructed shapes lifted from tests/test_candlestick.py "
        "+ degenerate cases + empty",
        "thresholds": THRESHOLDS,
        "pattern_order": PATTERN_ORDER,
        "directions": DIRECTIONS,
        "cases": cases,
    }


def build_spy_fixture() -> Dict[str, Any]:
    df = _spy_like_frame()
    case = _build_case("spy_last_2000", df, with_diagnostics=True)
    return {
        "schema": SCHEMA,
        "source": "backtest/run_candlestick_fixture_export.py",
        "generated_from": (
            "SYNTHETIC: data/SPY_daily.csv is not committed in this checkout "
            f"(data/ is gitignored) -- deterministic geometric-Brownian-motion series, "
            f"seed={SPY_FIXTURE_SEED}, bars={SPY_FIXTURE_BARS}. See module docstring."
        ),
        "thresholds": THRESHOLDS,
        "pattern_order": PATTERN_ORDER,
        "directions": DIRECTIONS,
        "cases": [case],
    }


def _check_coverage(shapes: Dict[str, Any], spy: Dict[str, Any]) -> None:
    """Raise unless, across the union of all cases in both fixtures, every one of the
    14 detectors has >=1 fire and >=1 non-fire. Guards against a green-on-all-false (or
    green-on-all-true) illusion of parity."""
    has_fire = {name: False for name in PATTERN_ORDER}
    has_non_fire = {name: False for name in PATTERN_ORDER}
    for fixture in (shapes, spy):
        for case in fixture["cases"]:
            n = len(case["bars"])
            for name in PATTERN_ORDER:
                fired = case["fires"][name]
                if fired:
                    has_fire[name] = True
                if len(fired) < n:
                    has_non_fire[name] = True
    missing_fire = [n for n, v in has_fire.items() if not v]
    missing_non_fire = [n for n, v in has_non_fire.items() if not v]
    if missing_fire or missing_non_fire:
        raise ValueError(
            "candlestick fixture coverage rule violated -- "
            f"detectors with zero fires: {missing_fire}; "
            f"detectors with zero non-fires: {missing_non_fire}"
        )


def _dump(obj: Dict[str, Any], path: Path) -> None:
    # allow_nan=False: NaN must already be mapped to null (see _sma_json) -- Python's
    # default json.dump emits a bare NaN token, which Deno's JSON.parse rejects outright.
    text = json.dumps(obj, indent=2, allow_nan=False, sort_keys=False)
    path.write_text(text + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--out", required=True, help="output directory for the two fixture JSON files"
    )
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    shapes = build_shapes_fixture()
    spy = build_spy_fixture()
    _check_coverage(shapes, spy)

    _dump(shapes, out_dir / "candlestick-golden-shapes.json")
    _dump(spy, out_dir / "candlestick-golden-spy.json")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
