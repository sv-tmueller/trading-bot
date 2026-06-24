"""Candidate strategy survey runner — #314 (first cut).

Screens two published low-turnover families (Antonacci GEM dual-momentum and
Faber MA-timing, single-asset + 5-asset GTAA) against 1x SPY buy-and-hold and
the four #255 dumb baselines, on the #263 walk-forward harness + cost model,
through the after-tax layer in BOTH passes and BOTH jurisdictions.

Two tax passes (the #313 logged decision):
  - full-history after-tax equity curve: one long simulation per strategy, so
    a buy-and-hold lot can qualify for the US long-term rate while churning
    families realize short-term. The recommendation is RANKED on full-history
    after-tax Calmar.
  - per-window after-tax: each non-overlapping 12-month OOS window simulated
    independently (the #263 no-curve-fit stability gate). By construction every
    per-window lot is held < 12 months -> all US-short-term; that is expected
    and is exactly why the full-history pass exists.

Window comparability (the load-bearing choice): each family is screened over
its OWN longest-common-window (set by the deepest-inception asset it needs), and
1x SPY + the four baselines are RECOMPUTED inside that same window. An after-tax
Calmar from a 2007-start window is not comparable to one from 1993, so the
"beats SPY?" verdict for each family is made strictly within that family's
window. SPY/baseline rows therefore differ per family block — that is correct.

All strategies run unleveraged (weights <= 1; vehicle=SPY for the single-asset
rows) so the screen is a clean 1x comparison. The live 3x UPRO incumbent is
context for the recommendation, not a row in this 1x screen.

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
No LLM, no broker calls.

Run:
    python3 -m backtest.run_candidate_survey
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from backtest.baselines import (
    buy_and_hold_signal,
    faber_sma_signal,
    persistence_signal,
    tsmom_signal,
)
from backtest.families import (
    faber_gtaa_weights,
    faber_single_weights,
    gem_weights,
)
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal
from backtest.tax import apply_tax_to_ledger
from backtest.walkforward import _compute_window_metrics, _slice_windows

STARTING_CASH = 100_000.0
_MAX_LOOKBACK_DAYS = 300  # >= GEM 12-month + Faber 10-month + 200-DMA warm-ups

# Bear sub-windows presented explicitly per family (drawdown + recovery).
_BEAR_WINDOWS = {
    "2020 COVID": (date(2020, 2, 1), date(2020, 12, 31)),
    "2022 bear": (date(2022, 1, 1), date(2022, 12, 31)),
}


def _fetch(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch auto-adjusted Open/Close from yfinance (patchable for tests)."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def _fetch_universe(tickers: list[str], end: date) -> dict:
    """Fetch every ticker from 1990 to ``end``. Returns {ticker: OHLC frame}.

    Fetches from a very early start so each ticker's true inception bounds the
    common window (no fabricated history — a ticker simply starts when it
    starts).
    """
    out: dict = {}
    for t in tickers:
        df = _fetch(t, date(1990, 1, 1), end)
        if len(df) == 0:
            raise RuntimeError(f"no data for {t} — cannot run survey (BLOCKED)")
        out[t] = df
    return out


def _common_index(frames: list[pd.DataFrame]) -> pd.DatetimeIndex:
    """Intersection of the indices of several OHLC frames."""
    idx = frames[0].index
    for f in frames[1:]:
        idx = idx.intersection(f.index)
    return idx


def _years(idx: pd.DatetimeIndex) -> float:
    return (idx[-1] - idx[0]).days / 365.25


def _curve_metrics(curve: pd.Series) -> dict:
    """CAGR / maxDD / Calmar on an equity curve, robust to capital wipe-out.

    Uses the foundation's conventions (calendar-span CAGR, Calmar = CAGR/|maxDD|,
    NaN when maxDD == 0). The one case the foundation's ``_compute_window_metrics``
    cannot express is an after-tax curve that goes non-positive: the no-loss-credit
    tax model can tax gross winners on a strategy whose gross losers dominate,
    driving after-tax equity below zero. ``(1 + total_return)`` is then < 0 and a
    fractional power is complex — undefined. Here that case reports CAGR/Calmar as
    NaN with maxDD clamped at -100% (capital ruined), so the survey records the
    ruin honestly instead of crashing. The pre-tax (long-only, cash-floored) curve
    never hits this branch.
    """
    start = float(curve.iloc[0])
    end = float(curve.iloc[-1])
    rolling_max = curve.cummax()
    max_dd = float(((curve - rolling_max) / rolling_max).min())

    if end <= 0 or start <= 0:
        # capital wiped out at/after some exit -> CAGR/Calmar undefined
        return {"cagr": float("nan"), "max_drawdown": min(max_dd, -1.0),
                "calmar": float("nan")}

    total_return = end / start - 1.0
    span_years = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = float((1.0 + total_return) ** (1.0 / span_years) - 1.0) if span_years > 0 else 0.0
    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else float("nan")
    return {"cagr": cagr, "max_drawdown": max_dd, "calmar": calmar}


def _after_tax_metrics(sim: dict, idx: pd.DatetimeIndex) -> dict:
    """Pre-tax + US/DE after-tax CAGR/Calmar/maxDD on the FULL equity curve.

    Pre-tax metrics reuse the foundation's ``_compute_window_metrics`` directly.
    After-tax metrics use ``_curve_metrics`` (same conventions, ruin-safe) because
    a high-churn after-tax curve can go non-positive under the no-loss-credit tax
    model — see ``_curve_metrics``. No "x (1 - tau)" shortcut; the real after-tax
    drawdown shifts as tax steps in at each exit.
    """
    eq = sim["equity_curve"]
    trades = sim["trades"]
    pretax = _compute_window_metrics(eq, trades, STARTING_CASH)

    after_us = apply_tax_to_ledger(trades, eq, jurisdiction="US")
    after_de = apply_tax_to_ledger(trades, eq, jurisdiction="DE")
    m_us = _curve_metrics(after_us)
    m_de = _curve_metrics(after_de)

    yrs = _years(idx)
    turnover = sim["trade_count"] / yrs if yrs > 0 else float("nan")

    return {
        "cagr_pretax": pretax["cagr"],
        "max_dd": pretax["max_drawdown"],
        "calmar_pretax": pretax["calmar"],
        "calmar_us": m_us["calmar"],
        "calmar_de": m_de["calmar"],
        "cagr_us": m_us["cagr"],
        "cagr_de": m_de["cagr"],
        "max_dd_us": m_us["max_drawdown"],
        "trade_count": sim["trade_count"],
        "turnover_yr": turnover,
    }


# ---------------------------------------------------------------------------
# Strategy runners — each returns a full-window simulate_from_signal result.
# ---------------------------------------------------------------------------

def _sim_single_asset(spy: pd.DataFrame, signal: pd.Series) -> dict:
    """Run a binary single-asset (vehicle=SPY) signal over its full index."""
    return simulate_from_signal(
        vehicle_df=spy,
        is_bullish_close_t=signal,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )


def _sim_weighted(weights: pd.DataFrame, asset_px: dict) -> dict:
    """Run a multi-asset target-weight frame over its full index."""
    return simulate_from_signal(
        target_weights=weights,
        asset_px=asset_px,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )


def _baseline_rows(spy: pd.DataFrame, idx: pd.DatetimeIndex) -> dict:
    """1x SPY B&H + the four dumb baselines, all vehicle=SPY, over ``idx``.

    Returns {label: full-window simulate result}. SPY closes drive every signal.
    """
    spy_w = spy.loc[idx]
    close = spy_w["Close"]
    rows = {
        "1x SPY (buy & hold)": _sim_single_asset(spy_w, buy_and_hold_signal(close)),
        "baseline: persistence": _sim_single_asset(spy_w, persistence_signal(close)),
        "baseline: faber 10mo": _sim_single_asset(spy_w, faber_sma_signal(close)),
        "baseline: tsmom 12mo": _sim_single_asset(spy_w, tsmom_signal(close)),
    }
    return rows


# ---------------------------------------------------------------------------
# Per-window stability pass (the #263 no-curve-fit gate).
# ---------------------------------------------------------------------------

def _per_window_after_tax_calmar(
    *,
    strategy: str,
    universe: dict,
    held_assets: list[str],
    common_idx: pd.DatetimeIndex,
    window_months: int = 12,
) -> dict:
    """Median per-window after-tax (US) Calmar + count of positive-Calmar windows.

    Each OOS window resets to STARTING_CASH with a max-lookback pre-roll for
    signal warm-up; metrics are taken on the test sub-window only (Trap A).
    By construction every per-window lot is held < window_months -> US-short-term.
    """
    windows = _slice_windows(
        all_dates=common_idx,
        test_start=common_idx[0].date(),
        window_months=window_months,
        max_lookback_days=_MAX_LOOKBACK_DAYS,
    )
    calmars: list[float] = []
    for pr_start, ts, te in windows:
        mask = (common_idx >= pr_start) & (common_idx <= te)
        widx = common_idx[mask]
        if len(widx) < 30:
            continue
        sim = _simulate_strategy_on_index(strategy, universe, held_assets, widx)
        eq = sim["equity_curve"]
        test_mask = (eq.index >= ts) & (eq.index <= te)
        eq_test = eq.loc[test_mask]
        if len(eq_test) < 2:
            continue
        test_trades = [t for t in sim["trades"] if ts <= t["exit_date"] <= te]
        after_us = apply_tax_to_ledger(test_trades, eq_test, jurisdiction="US")
        m = _curve_metrics(after_us)
        c = m["calmar"]
        if not (isinstance(c, float) and np.isnan(c)):
            calmars.append(c)
    if not calmars:
        return {"median_calmar": float("nan"), "n_windows": 0, "n_positive": 0}
    arr = np.array(calmars, dtype=float)
    return {
        "median_calmar": float(np.median(arr)),
        "n_windows": len(arr),
        "n_positive": int((arr > 0).sum()),
    }


def _simulate_strategy_on_index(
    strategy: str,
    universe: dict,
    held_assets: list[str],
    idx: pd.DatetimeIndex,
) -> dict:
    """Build the strategy's signal/weights on ``idx`` and simulate it.

    ``strategy`` is one of: 'gem', 'faber_single', 'gtaa', '1x_spy',
    'persistence', 'faber10', 'tsmom'.
    """
    spy = universe["SPY"].loc[idx]
    close = spy["Close"]
    if strategy == "1x_spy":
        return _sim_single_asset(spy, buy_and_hold_signal(close))
    if strategy == "persistence":
        return _sim_single_asset(spy, persistence_signal(close))
    if strategy == "faber10":
        return _sim_single_asset(spy, faber_sma_signal(close))
    if strategy == "tsmom":
        return _sim_single_asset(spy, tsmom_signal(close))
    if strategy == "faber_single":
        w = faber_single_weights(close, idx)
        return _sim_weighted(w, {"SPY": spy})
    if strategy == "gem":
        asset_close = {a: universe[a]["Close"].loc[idx] for a in held_assets}
        asset_close["BIL"] = universe["BIL"]["Close"].reindex(idx).ffill()
        w = gem_weights(asset_close, idx)
        asset_px = {a: universe[a].loc[idx] for a in held_assets}
        return _sim_weighted(w, asset_px)
    if strategy == "gtaa":
        asset_close = {a: universe[a]["Close"].loc[idx] for a in held_assets}
        w = faber_gtaa_weights(asset_close, idx, assets=tuple(held_assets))
        asset_px = {a: universe[a].loc[idx] for a in held_assets}
        return _sim_weighted(w, asset_px)
    raise ValueError(f"unknown strategy {strategy!r}")


# ---------------------------------------------------------------------------
# Bear-stress slices.
# ---------------------------------------------------------------------------

def _bear_stress(
    strategy: str,
    universe: dict,
    held_assets: list[str],
    common_idx: pd.DatetimeIndex,
) -> dict:
    """Max drawdown of ``strategy`` in each bear sub-window (if covered)."""
    out: dict = {}
    for label, (b0, b1) in _BEAR_WINDOWS.items():
        # include a pre-roll for warm-up, then measure only inside the bear window
        pr0 = pd.Timestamp(b0) - pd.DateOffset(days=_MAX_LOOKBACK_DAYS * 2)
        mask = (common_idx >= pr0) & (common_idx <= pd.Timestamp(b1))
        widx = common_idx[mask]
        in_bear = (widx >= pd.Timestamp(b0)) & (widx <= pd.Timestamp(b1))
        if in_bear.sum() < 20:
            out[label] = None  # not enough coverage in this family's window
            continue
        sim = _simulate_strategy_on_index(strategy, universe, held_assets, widx)
        eq = sim["equity_curve"]
        eq_bear = eq.loc[(eq.index >= pd.Timestamp(b0)) & (eq.index <= pd.Timestamp(b1))]
        if len(eq_bear) < 2:
            out[label] = None
            continue
        roll = eq_bear.cummax()
        dd = float(((eq_bear - roll) / roll).min())
        ret = float(eq_bear.iloc[-1] / eq_bear.iloc[0] - 1)
        out[label] = {"max_dd": dd, "window_return": ret}
    return out


# ---------------------------------------------------------------------------
# Family definitions (assets + the deepest-inception ticker that binds it).
# ---------------------------------------------------------------------------

FAMILIES = [
    {
        "key": "gem",
        "label": "GEM dual-momentum (SPY/EFA/AGG; BIL hurdle)",
        "held": ["SPY", "EFA", "AGG"],
        "binding": ["SPY", "EFA", "AGG", "BIL"],  # BIL is the hurdle (not held)
    },
    {
        "key": "faber_single",
        "label": "Faber 10mo SMA (single-asset SPY)",
        "held": ["SPY"],
        "binding": ["SPY"],
    },
    {
        "key": "gtaa",
        "label": "Faber GTAA-lite (SPY/EFA/AGG/DBC/VNQ)",
        "held": ["SPY", "EFA", "AGG", "DBC", "VNQ"],
        "binding": ["SPY", "EFA", "AGG", "DBC", "VNQ"],
    },
]

ALL_TICKERS = ["SPY", "EFA", "AGG", "BIL", "DBC", "VNQ"]


def run_survey(end: Optional[date] = None) -> dict:
    """Fetch data, run every family + 1x SPY + baselines through both passes.

    Returns a nested dict: per family, the family row + the per-family baseline
    rows, the per-window stability, and the bear-stress slices.
    """
    end = end or date.today()
    print(f"Fetching universe {ALL_TICKERS} (1990 -> {end}) ...", flush=True)
    universe = _fetch_universe(ALL_TICKERS, end)
    for t in ALL_TICKERS:
        print(f"  {t:5s} {universe[t].index[0].date()} -> {universe[t].index[-1].date()} "
              f"({len(universe[t])} rows)", flush=True)

    results: dict = {}
    for fam in FAMILIES:
        binding_frames = [universe[t] for t in fam["binding"]]
        common = _common_index(binding_frames)
        if len(common) < 300:
            results[fam["key"]] = {"error": "insufficient common history"}
            continue

        held = fam["held"]
        fam_sim = _simulate_strategy_on_index(fam["key"], universe, held, common)
        fam_metrics = _after_tax_metrics(fam_sim, common)

        # 1x SPY + baselines recomputed inside THIS family's window
        spy_aligned = universe["SPY"].loc[common]
        base_sims = _baseline_rows(spy_aligned, common)
        base_metrics = {
            lbl: _after_tax_metrics(sim, common) for lbl, sim in base_sims.items()
        }

        stability = _per_window_after_tax_calmar(
            strategy=fam["key"], universe=universe, held_assets=held,
            common_idx=common,
        )
        # baseline 1x SPY per-window stability for the same window (comparison)
        spy_stability = _per_window_after_tax_calmar(
            strategy="1x_spy", universe=universe, held_assets=["SPY"],
            common_idx=common,
        )

        bear = _bear_stress(fam["key"], universe, held, common)
        spy_bear = _bear_stress("1x_spy", universe, ["SPY"], common)

        results[fam["key"]] = {
            "label": fam["label"],
            "window": (common[0].date(), common[-1].date()),
            "n_days": len(common),
            "family": fam_metrics,
            "baselines": base_metrics,
            "stability": stability,
            "spy_stability": spy_stability,
            "bear": bear,
            "spy_bear": spy_bear,
        }
    return results


def _fmt(x: float, pct: bool = False, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    if pct:
        return f"{x*100:+.1f}%"
    return f"{x:.{nd}f}"


def _print_report(results: dict) -> None:
    print("\n" + "=" * 100)
    print("CANDIDATE STRATEGY SURVEY — full-history after-tax Calmar (ranked within each window)")
    print("=" * 100)

    for key, r in results.items():
        if "error" in r:
            print(f"\n### {key}: {r['error']}")
            continue
        w0, w1 = r["window"]
        print(f"\n### {r['label']}")
        print(f"Window: {w0} -> {w1}  ({r['n_days']} trading days, "
              f"~{(w1 - w0).days / 365.25:.1f}y)")

        # Assemble rows: family first, then SPY + baselines (this window)
        rows = [("FAMILY: " + r["label"], r["family"])]
        for lbl, m in r["baselines"].items():
            rows.append((lbl, m))

        spy_m = r["baselines"]["1x SPY (buy & hold)"]
        spy_calmar_us = spy_m["calmar_us"]

        header = (f"{'strategy':<46} {'Calmar US':>9} {'Calmar DE':>9} "
                  f"{'CAGR':>7} {'maxDD':>8} {'trd/yr':>7} {'>1xSPY?':>8}")
        print(header)
        print("-" * len(header))
        for lbl, m in rows:
            beats = ""
            if not lbl.startswith("1x SPY"):
                bc = m["calmar_us"]
                if isinstance(bc, float) and np.isnan(bc):
                    beats = "n/a"
                elif isinstance(spy_calmar_us, float) and np.isnan(spy_calmar_us):
                    beats = "n/a"
                else:
                    beats = "YES" if bc > spy_calmar_us else "no"
            print(f"{lbl:<46} {_fmt(m['calmar_us']):>9} {_fmt(m['calmar_de']):>9} "
                  f"{_fmt(m['cagr_pretax'], pct=True):>7} {_fmt(m['max_dd'], pct=True):>8} "
                  f"{_fmt(m['turnover_yr']):>7} {beats:>8}")

        # Per-window stability gate
        st = r["stability"]
        sst = r["spy_stability"]
        print(f"\nPer-window after-tax (US) stability gate (12mo OOS windows):")
        print(f"  family : median Calmar {_fmt(st['median_calmar'])}  "
              f"({st['n_positive']}/{st['n_windows']} windows positive)")
        print(f"  1x SPY : median Calmar {_fmt(sst['median_calmar'])}  "
              f"({sst['n_positive']}/{sst['n_windows']} windows positive)")

        # Bear stress
        print(f"\nBear stress (max drawdown / window return; vs 1x SPY same window):")
        for lbl in _BEAR_WINDOWS:
            fb = r["bear"].get(lbl)
            sb = r["spy_bear"].get(lbl)
            if fb is None:
                print(f"  {lbl:<12}: not covered in this family's window")
                continue
            sbtxt = (f"SPY {_fmt(sb['max_dd'], pct=True)}/{_fmt(sb['window_return'], pct=True)}"
                     if sb else "SPY n/a")
            survives = "SURVIVES" if (sb and fb["max_dd"] >= sb["max_dd"]) else "worse than SPY"
            print(f"  {lbl:<12}: family DD {_fmt(fb['max_dd'], pct=True)} "
                  f"ret {_fmt(fb['window_return'], pct=True)}  |  {sbtxt}  -> {survives}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_candidate_survey")
    parser.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today()

    results = run_survey(end=end)
    _print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
