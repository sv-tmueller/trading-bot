"""Scorecard metrics and markdown rendering for the AI research pipeline (Task 7).

Turns a ``PortfolioResult`` (candidate), a vol-targeted benchmark
``PortfolioResult`` and optional double-cost and 1.5x-exposure re-runs into the
plain dict that Task 8 (``pipeline_gate``) reads and Task 11 records, and
renders the spec 5.5 table. Research-only: lives in backtest/, is never
imported by supabase/functions/, makes no network or broker call and uses no
LLM. It imports only numpy, pandas, ``backtest.portfolio`` and
``backtest.tax`` (not ``backtest.regime``, which pulls in yfinance).

Shape contract (strict JSON, ``json.dumps(card, allow_nan=False)`` works):

- Plain float, int, str and None only. Dates are ISO ``YYYY-MM-DD`` strings,
  year keys are 4-digit strings, undefined values are None (never NaN/inf).
- ``max_drawdown`` is a non-negative magnitude (0.10 for a 10% drawdown).
- Returns, vols and costs are decimal fractions.
- ``sharpe_daily`` is mean/std(ddof=1) of the daily returns, not annualised
  and not excess; it equals ``overfitting_gate``'s ``sr_hat`` for the same
  finite series. ``n_periods`` is the number of finite return rows.
- Non-finite returns are dropped. The simulator's ``daily_returns`` is
  ``equity.pct_change()`` with row 0 set finite (``backtest/portfolio.py``), so
  a real result loses rows only once its equity sits at exactly 0.0 (NaN for
  0/0, inf for x/0); a raw ``pct_change()`` fixture also has NaN in row 0.
  Entries that are not finite
  are removed from ``sharpe_daily``, ``sharpe_annual``, ``realized_vol``,
  ``n_periods`` and ``year_returns`` (a dropped day counts as a 0% day), so
  every value stays finite. With fewer than 2 finite returns the Sharpe and
  vol are 0.0, the same convention as zero variance.
- ``costs["cash_interest"]`` is never read, so the scorecard is independent of
  how the simulator accrues cash interest.

Calendar-year Calmars (``window_calmars``, the repo's n_w convention, adapted
from ``run_mes_swing_study._per_window_scores``):

- Only full calendar years are scored: year Y counts when the index starts on
  or before Y-01-07 and ends on or after Y-12-25. A trailing or leading
  partial year is never scored. ``year_returns``, ``worst_year`` and
  ``window_calmars`` use the same set of years.
- Per year, the equity slice for Y is taxed with ``apply_annual_netting_tax``
  using only trades whose ``exit_date`` falls in Y (all kinds). Without that
  filter the tax layer's fallback branch would deduct other years' tax at the
  slice's last point.
- Years whose Calmar is undefined (zero drawdown) are left out.

Known differences from the per-window precedent (documented, no action):

- The windows are slices of one continuous run, so positions carry across
  Jan 1. A carried-in lot's whole pnl is taxed in the year it exits.
- The window Calmar starts at the first session's close, which excludes the
  return into that session. ``year_returns`` includes it.

``avg_holding_days`` averages ``round_trip`` trades only. Partial trades are
excluded, and so are positions still open at the end of the data, because the
simulator does no forced close-out.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.portfolio import PortfolioResult, round_trips_per_year
from backtest.tax import apply_annual_netting_tax

_TRADING_DAYS = 252
_ZERO_VARIANCE_ATOL = 1e-12
_NA = "n/a"

HEADER = "| Figure | Development (to 2021) | Holdout (2022+) |"

# First-column labels of spec 5.5, verbatim (also the template in
# docs/research/pipeline/README.md).
ROW_LABELS = (
    "CAGR (pre-tax, after costs)",
    "CAGR after German tax",
    "Max drawdown, and its dates",
    "Calmar (return / max drawdown)",
    "Sharpe; target and realised annualised volatility",
    "Worst calendar year; 2008 and 2020 (development), 2022 (holdout)",
    "Round trips per year, average holding days, max share of time in one ETF",
    "Cost drag per year, incl. short-borrow cost; result at double cost",
    "vs vol-targeted SPY benchmark (Calmar, CAGR, max DD)",
    "DSR (with programme trial count), PBO, bootstrap CI on uplift",
    "Same rule at 1.5x gross exposure, incl. financing (information only)",
)

_CRITERIA_ORDER = ("drawdown", "beats_benchmark", "luck", "holdout", "activity")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _years_between(idx: pd.DatetimeIndex) -> float:
    return (idx[-1] - idx[0]).days / 365.25


def _curve_metrics(curve: pd.Series) -> dict:
    """CAGR / drawdown / Calmar on an equity curve, robust to ruin.

    Follows ``run_candidate_survey._curve_metrics`` except that ``max_drawdown``
    is returned as a non-negative magnitude and undefined values are None. An
    after-tax curve can go non-positive under the no-loss-credit tax model; the
    CAGR and Calmar are then None and the drawdown magnitude is at least 1.0.
    """
    start = float(curve.iloc[0])
    end = float(curve.iloc[-1])
    if start <= 0:
        return {"cagr": None, "max_drawdown": 1.0, "start": None, "end": None, "calmar": None}

    running_max = curve.cummax()
    drawdown = (curve - running_max) / running_max
    max_dd = max(0.0, float(-drawdown.min()))  # 0.0 first: max(-0.0, 0.0) is -0.0
    dd_start: Optional[str] = None
    dd_end: Optional[str] = None
    if max_dd > 0.0:
        trough = drawdown.idxmin()  # first date that hits the minimum
        peak_value = running_max.loc[trough]
        before = curve.loc[:trough]
        dd_start = _iso(before.index[before.to_numpy() == peak_value][-1])
        dd_end = _iso(trough)

    if end <= 0:
        return {"cagr": None, "max_drawdown": max(max_dd, 1.0),
                "start": dd_start, "end": dd_end, "calmar": None}

    span_years = _years_between(curve.index)
    cagr = float((end / start) ** (1.0 / span_years) - 1.0) if span_years > 0 else None
    calmar = float(cagr / max_dd) if (cagr is not None and max_dd > 0.0) else None
    return {"cagr": cagr, "max_drawdown": max_dd, "start": dd_start, "end": dd_end,
            "calmar": calmar}


def _scored_years(idx: pd.DatetimeIndex) -> List[int]:
    """Full calendar years: index starts by Y-01-07 and ends on or after Y-12-25."""
    years = sorted(set(int(y) for y in idx.year))
    return [
        y for y in years
        if idx[0] <= pd.Timestamp(y, 1, 7) and idx[-1] >= pd.Timestamp(y, 12, 25)
    ]


def _window_calmars(res: PortfolioResult, years: List[int]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for y in years:
        eq_y = res.equity[res.equity.index.year == y]
        trades_y = [t for t in res.trades if pd.Timestamp(t["exit_date"]).year == y]
        calmar = _curve_metrics(apply_annual_netting_tax(trades_y, eq_y))["calmar"]
        if calmar is not None:
            out[str(y)] = calmar
    return out


def _finite(returns: pd.Series) -> np.ndarray:
    values = returns.to_numpy(dtype=float)
    return values[np.isfinite(values)]


def _performance_block(res: PortfolioResult) -> dict:
    """The 13 keys computed for both the candidate and the benchmark."""
    equity = res.equity
    r = _finite(res.daily_returns)
    pre = _curve_metrics(equity)
    after = _curve_metrics(apply_annual_netting_tax(res.trades, equity))

    std = float(r.std(ddof=1)) if len(r) >= 2 else 0.0
    sharpe_daily = 0.0 if std <= _ZERO_VARIANCE_ATOL else float(r.mean() / std)

    years = _scored_years(equity.index)
    year_returns = {
        str(y): float(np.prod(1.0 + _finite(res.daily_returns[equity.index.year == y])) - 1.0)
        for y in years
    }
    worst_year = None
    if year_returns:
        wy = min(year_returns, key=lambda k: year_returns[k])
        worst_year = {"year": wy, "return": year_returns[wy]}

    return {
        "cagr": pre["cagr"],
        "cagr_after_tax": after["cagr"],
        "max_drawdown": pre["max_drawdown"],
        "max_drawdown_start": pre["start"],
        "max_drawdown_end": pre["end"],
        "calmar": pre["calmar"],
        "sharpe_daily": sharpe_daily,
        "sharpe_annual": float(sharpe_daily * math.sqrt(_TRADING_DAYS)),
        "n_periods": int(len(r)),
        "realized_vol": float(std * math.sqrt(_TRADING_DAYS)),
        "year_returns": year_returns,
        "worst_year": worst_year,
        "window_calmars": _window_calmars(res, years),
    }


def _scenario_block(res: Optional[PortfolioResult]) -> Optional[dict]:
    if res is None:
        return None
    m = _curve_metrics(res.equity)
    return {"cagr": m["cagr"], "max_drawdown": m["max_drawdown"], "calmar": m["calmar"]}


def _max_time_share(held_weights: pd.DataFrame) -> float:
    if len(held_weights.columns) == 0 or len(held_weights) == 0:
        return 0.0
    return float((held_weights != 0.0).mean().max())


def _per_year(amount: float, equity: pd.Series) -> Optional[float]:
    years = _years_between(equity.index)
    mean_equity = float(equity.mean())
    if years <= 0 or mean_equity <= 0:
        return None
    return float(amount / mean_equity / years)


def compute_scorecard(
    result: PortfolioResult,
    benchmark: PortfolioResult,
    *,
    target_vol: float,
    double_cost: Optional[PortfolioResult] = None,
    leverage_info: Optional[PortfolioResult] = None,
) -> dict:
    """Build the scorecard dict for one phase (development or holdout).

    Raises ``ValueError`` when ``result`` has fewer than 2 rows, when
    ``target_vol`` is not finite and positive, or when the equity index of
    ``benchmark``, ``double_cost`` or ``leverage_info`` differs from
    ``result``'s (a silent period mismatch would corrupt the benchmark
    criterion).
    """
    if len(result.equity) < 2:
        raise ValueError("compute_scorecard needs at least 2 equity rows")
    if not (math.isfinite(target_vol) and target_vol > 0):
        raise ValueError(f"target_vol must be finite and > 0, got {target_vol!r}")
    for name, other in (("benchmark", benchmark), ("double_cost", double_cost),
                        ("leverage_info", leverage_info)):
        if other is not None and not result.equity.index.equals(other.equity.index):
            raise ValueError(f"{name} equity index does not match result's")

    card = _performance_block(result)
    trips = [t for t in result.trades if t["kind"] == "round_trip"]
    holding = [(pd.Timestamp(t["exit_date"]) - pd.Timestamp(t["entry_date"])).days for t in trips]
    costs = result.costs
    card.update({
        "target_vol": float(target_vol),
        "round_trips_per_year": float(round_trips_per_year(result)),
        "avg_holding_days": float(np.mean(holding)) if holding else None,
        "max_time_share_one_etf": _max_time_share(result.held_weights),
        "cost_drag_per_year": _per_year(
            float(costs["trading"]) + float(costs["borrow"]) + float(costs["financing"]),
            result.equity),
        "borrow_cost_per_year": _per_year(float(costs["borrow"]), result.equity),
        "benchmark": _performance_block(benchmark),
        "double_cost": _scenario_block(double_cost),
        "leverage_info": _scenario_block(leverage_info),
    })
    return card


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _pct(x: Optional[float]) -> str:
    return _NA if x is None else f"{x * 100:.1f}%"


def _num(x: Optional[float], digits: int = 2) -> str:
    return _NA if x is None else f"{x:.{digits}f}"


def _scenario_text(block: Optional[dict]) -> str:
    if block is None:
        return _NA
    return (f"CAGR {_pct(block.get('cagr'))}, max DD {_pct(block.get('max_drawdown'))}, "
            f"Calmar {_num(block.get('calmar'))}")


def _median(values: Dict[str, float]) -> Optional[float]:
    return float(np.median(list(values.values()))) if values else None


def _column(card: dict, years: tuple, dsr_text: str) -> List[str]:
    """The 11 cells of one phase column, in ROW_LABELS order."""
    bench = card.get("benchmark") or {}
    worst = card.get("worst_year")
    year_returns = card.get("year_returns") or {}
    window = card.get("window_calmars") or {}
    bench_window = bench.get("window_calmars") or {}

    dd = _pct(card.get("max_drawdown"))
    if card.get("max_drawdown_start") and card.get("max_drawdown_end"):
        dd += f" ({card['max_drawdown_start']} to {card['max_drawdown_end']})"

    worst_text = f"worst {worst['year']} {_pct(worst['return'])}" if worst else "worst n/a"
    year_text = "; ".join(f"{y} {_pct(year_returns.get(y))}" for y in years)

    return [
        _pct(card.get("cagr")),
        _pct(card.get("cagr_after_tax")),
        dd,
        _num(card.get("calmar")),
        (f"Sharpe {_num(card.get('sharpe_annual'))}; target {_pct(card.get('target_vol'))}, "
         f"realised {_pct(card.get('realized_vol'))}"),
        f"{worst_text}; {year_text}",
        (f"{_num(card.get('round_trips_per_year'), 1)} round trips/yr; "
         f"{_num(card.get('avg_holding_days'), 1)} avg holding days; "
         f"{_pct(card.get('max_time_share_one_etf'))} max share in one ETF"),
        (f"cost drag {_pct(card.get('cost_drag_per_year'))}/yr "
         f"(borrow {_pct(card.get('borrow_cost_per_year'))}/yr); "
         f"double cost: {_scenario_text(card.get('double_cost'))}"),
        (f"benchmark Calmar {_num(bench.get('calmar'))}, CAGR {_pct(bench.get('cagr'))}, "
         f"max DD {_pct(bench.get('max_drawdown'))}; median after-tax year Calmar "
         f"{_num(_median(window))} vs {_num(_median(bench_window))} "
         f"(n_w={len(window)})"),
        dsr_text,
        _scenario_text(card.get("leverage_info")),
    ]


def render_scorecard_markdown(
    development: dict,
    holdout: Optional[dict],
    verdict: Optional[dict],
) -> str:
    """Render the spec 5.5 table, plus the per-criterion verdict when given.

    The holdout column is ``n/a`` throughout when ``holdout`` is None, and the
    DSR row's holdout cell is always ``n/a``. A None value inside a present dict
    renders as ``n/a``. DSR, PBO and the bootstrap CI are not held by the
    scorecard; the development DSR cell shows the ``luck`` criterion's detail
    from ``verdict`` when one is passed. No recommendation text lives here.
    """
    dsr_text = _NA
    if verdict is not None:
        luck = (verdict.get("criteria") or {}).get("luck")
        if luck is not None:
            dsr_text = str(luck.get("detail", _NA))

    dev_cells = _column(development, ("2008", "2020"), dsr_text)
    if holdout is None:
        hold_cells = [_NA] * len(ROW_LABELS)
    else:
        hold_cells = _column(holdout, ("2022",), _NA)
    hold_cells[9] = _NA

    lines = [HEADER, "|---|---|---|"]
    for label, dev, hold in zip(ROW_LABELS, dev_cells, hold_cells):
        lines.append(f"| {_esc(label)} | {_esc(dev)} | {_esc(hold)} |")

    if verdict is not None:
        criteria = verdict.get("criteria") or {}
        lines += ["", f"**Verdict: {'PASS' if verdict.get('passed') else 'FAIL'}**", ""]
        for name in _CRITERIA_ORDER:
            crit = criteria.get(name)
            if crit is None:
                lines.append(f"- {name}: {_NA}")
            else:
                status = "pass" if crit.get("passed") else "fail"
                lines.append(f"- {name}: {status} ({crit.get('detail', '')})")
    return "\n".join(lines) + "\n"
