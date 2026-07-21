"""Live-vs-simulated divergence report (#403).

Replays the production 200-DMA rule through the existing backtest execution
model (``simulate_from_signal``) over the live trading window and compares
the simulated equity path against the live record — daily equity in
``equity_snapshots`` and actual fills in ``trades`` (both exported to CSV by
``scripts/export_live_history.sh``, never read directly from the DB here).

This module is research-only. It lives in backtest/ and must never be
imported by supabase/functions/. No LLM, no broker calls, no Supabase/Alpaca
imports of any kind — the only network-capable code is the ``_fetch`` seam
below (yfinance), exactly like backtest/walkforward.py.

Usage
-----
    venv/bin/python -m backtest.run_live_divergence --export-dir live_export/
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal

# Pre-roll so the 200-DMA signal is valid from the first live snapshot date
# (mirrors backtest/walkforward.py's _MAX_LOOKBACK_DAYS idiom).
_MAX_LOOKBACK_DAYS = 300

_TRADE_COLUMNS = [
    "fill_time", "symbol", "side", "qty", "fill_price", "reason", "broker_order_id",
]
_REGIME_COLUMNS = [
    "date", "spy_close", "spy_sma200", "target_state", "current_state", "kill_switch_active",
]
_AUDIT_COLUMNS = ["started_at", "finished_at", "outcome", "notes"]
_EQUITY_COLUMNS = ["date", "equity_usd"]


def _fetch(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch Open/Close from yfinance. Patchable seam for offline tests."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def _read_csv_tolerant(path: Path, columns: list[str], parse_dates: Optional[list[str]] = None) -> pd.DataFrame:
    """Read a CSV, tolerating a 0-byte file (no rows exported at all)."""
    try:
        return pd.read_csv(path, parse_dates=parse_dates)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns)


def load_live_export(export_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load the four CSVs written by scripts/export_live_history.sh.

    Returns a dict of DataFrames keyed by table name: equity_snapshots,
    trades, regime_state, audit_log. Dates are parsed; numeric columns are
    coerced. An empty (0-byte) CSV — e.g. no fills yet, or no daily-check
    audit rows in the window — yields an empty DataFrame with the expected
    columns rather than raising.
    """
    export_dir = Path(export_dir)

    equity = _read_csv_tolerant(
        export_dir / "equity_snapshots.csv", _EQUITY_COLUMNS, parse_dates=["date"],
    )
    if not equity.empty:
        equity["equity_usd"] = pd.to_numeric(equity["equity_usd"])

    trades = _read_csv_tolerant(export_dir / "trades.csv", _TRADE_COLUMNS)
    if not trades.empty:
        trades["fill_price"] = pd.to_numeric(trades["fill_price"])
        trades["qty"] = pd.to_numeric(trades["qty"])

    regime_state = _read_csv_tolerant(
        export_dir / "regime_state.csv", _REGIME_COLUMNS, parse_dates=["date"],
    )
    if not regime_state.empty:
        regime_state["spy_close"] = pd.to_numeric(regime_state["spy_close"])
        regime_state["spy_sma200"] = pd.to_numeric(regime_state["spy_sma200"])

    audit_log = _read_csv_tolerant(
        export_dir / "audit_log.csv", _AUDIT_COLUMNS, parse_dates=["started_at", "finished_at"],
    )

    return {
        "equity_snapshots": equity,
        "trades": trades,
        "regime_state": regime_state,
        "audit_log": audit_log,
    }


def replay_signal(spy_df: pd.DataFrame, sma_days: int = 200) -> pd.Series:
    """The 200-DMA signal at close-T, unshifted (matches computeTargetState).

    Strict ``>`` (equality is bearish, per config.ts / regime.ts). NaN during
    the SMA warm-up period is treated as False (no signal yet) — same
    convention as backtest/walkforward.py and backtest/regime.py.
    """
    close = spy_df["Close"]
    sma = close.rolling(sma_days).mean()
    return (close > sma).fillna(False)


def compute_tracking(
    live_snap: pd.DataFrame,
    sim_equity: pd.Series,
    starting_cash: Optional[float] = None,
) -> dict:
    """Tracking-error stats between the live equity record and the replay.

    ``live_snap`` has ``date``/``equity_usd`` columns (as loaded by
    ``load_live_export``); ``sim_equity`` is a date-indexed Series (the
    ``equity_curve`` from ``simulate_from_signal``, sliced to the comparison
    window). Compares on the inner-joined (common) dates.

    ``terminal_return_diff``/``terminal_equity_ratio`` (and the daily-gap
    stats) are **close-normalized**: each curve is expressed as a return
    relative to *its own* first common-date value. That normalization is an
    artifact when the two curves' first common date does not fall on
    literally identical starting cash for both — e.g. the go-live-ramp
    Trap-A restart, where the sim's tracking window can already open with a
    day-1 execution loss baked into its own first value, silently excluding
    that loss from the close-normalized comparison (#403 finding 1). When
    ``starting_cash`` is supplied, this also returns
    ``terminal_return_diff_cash_normalized`` — ``(live_final - sim_final) /
    starting_cash`` — anchored to the shared cash amount both curves actually
    started from, not each curve's own first-common-date value.
    """
    live = live_snap.copy()
    live["date"] = pd.to_datetime(live["date"])
    live = live.set_index("date")["equity_usd"].sort_index()
    sim = sim_equity.sort_index()

    common = live.index.intersection(sim.index)
    if len(common) < 2:
        raise ValueError(
            f"insufficient overlapping dates for tracking computation ({len(common)} found)"
        )

    live_c = live.loc[common]
    sim_c = sim.loc[common]

    live_ret = live_c / live_c.iloc[0] - 1
    sim_ret = sim_c / sim_c.iloc[0] - 1
    gap = live_ret - sim_ret

    daily_live_ret = live_c.pct_change().dropna()
    daily_sim_ret = sim_c.pct_change().dropna()
    daily_diff = (daily_live_ret - daily_sim_ret).dropna()

    result = {
        "n_days": int(len(common)),
        "terminal_return_diff": float(live_ret.iloc[-1] - sim_ret.iloc[-1]),
        "terminal_equity_ratio": float(live_c.iloc[-1] / sim_c.iloc[-1]),
        "mean_abs_daily_gap": float(gap.abs().mean()),
        "max_abs_daily_gap": float(gap.abs().max()),
        "daily_return_diff_std": (
            float(daily_diff.std(ddof=1)) if len(daily_diff) >= 2 else 0.0
        ),
    }
    if starting_cash is not None:
        result["terminal_return_diff_cash_normalized"] = float(
            (live_c.iloc[-1] - sim_c.iloc[-1]) / starting_cash
        )
    return result


_FILL_SLIPPAGE_COLUMNS = [
    "fill_time", "symbol", "side", "qty", "fill_price", "open_price",
    "cost_bps", "delta_vs_slippage_bps", "delta_vs_total_bps",
]


def compute_fill_slippage(trades_df: pd.DataFrame, vehicle_df: pd.DataFrame) -> pd.DataFrame:
    """Per-fill realized slippage (bps) vs the same-day open, vs modeled costs.

    ``cost_bps`` is signed so a positive value always means "cost you money
    relative to the day's open" for both BUY (filled above open) and SELL
    (filled below open) — directly comparable to the modeled
    ``SLIPPAGE_BPS`` (one-way) and ``SLIPPAGE_BPS + COMMISSION_BPS`` (total)
    constants from backtest/regime.py. A fill with no matching same-day
    vehicle bar (should not happen with a real yfinance history, but
    defensive against a data gap) is skipped.
    """
    if trades_df.empty:
        return pd.DataFrame(columns=_FILL_SLIPPAGE_COLUMNS)

    rows = []
    for _, t in trades_df.iterrows():
        fill_date = pd.Timestamp(t["fill_time"]).tz_localize(None).normalize()
        if fill_date not in vehicle_df.index:
            continue
        open_px = float(vehicle_df.loc[fill_date, "Open"])
        if open_px == 0:
            continue
        fill_price = float(t["fill_price"])
        direction = 1.0 if t["side"] == "BUY" else -1.0
        cost_bps = direction * (fill_price - open_px) / open_px * 1e4

        rows.append({
            "fill_time": t["fill_time"],
            "symbol": t["symbol"],
            "side": t["side"],
            "qty": t["qty"],
            "fill_price": fill_price,
            "open_price": open_px,
            "cost_bps": cost_bps,
            "delta_vs_slippage_bps": cost_bps - SLIPPAGE_BPS,
            "delta_vs_total_bps": cost_bps - (SLIPPAGE_BPS + COMMISSION_BPS),
        })

    return pd.DataFrame(rows, columns=_FILL_SLIPPAGE_COLUMNS)


def _join_audit_values(a: object, b: object) -> Optional[str]:
    """Join two same-day audit_log field values with ``"; "``, skipping
    None/NaN/empty parts. Used to aggregate a two-slot day's outcomes/notes
    instead of the later invocation silently overwriting the earlier one."""
    parts = []
    for v in (a, b):
        if v is None:
            continue
        if isinstance(v, float) and pd.isna(v):
            continue
        s = str(v)
        if s == "":
            continue
        parts.append(s)
    if not parts:
        return a if a is not None else b
    return "; ".join(parts)


def compute_divergence_dates(
    regime_state_df: pd.DataFrame,
    replayed_signal: pd.Series,
    audit_df: pd.DataFrame,
    *,
    benchmark_close: Optional[pd.Series] = None,
    sma_days: int = 200,
) -> pd.DataFrame:
    """Per-date signal- and execution-parity comparison against the replay.

    For each live ``regime_state`` row (date D), the "replayed target" is
    LONG iff the replayed signal at the last trading day strictly before D
    (in ``replayed_signal``'s index) is True — this matches how daily-check
    stores the *previous session's* spy_close/spy_sma200 on a row dated D.

    Returns one row per live regime_state date (not just mismatches) with
    boolean ``signal_mismatch`` (vs ``target_state``) and
    ``execution_mismatch`` (vs ``current_state``) columns, that day's
    daily-check ``outcome``/``notes`` (matched by date, if present in
    ``audit_df``), and — when ``benchmark_close`` is supplied — the % drift
    of the recorded ``spy_close``/``spy_sma200`` vs the yfinance value for
    the same prior trading day (Alpaca-vs-yfinance data-source drift).
    Callers filter to the mismatched rows for the "divergence dates" table
    and take ``.abs().max()`` over the diff columns for the drift stat.
    """
    sig_index = replayed_signal.index
    sma = benchmark_close.rolling(sma_days).mean() if benchmark_close is not None else None

    audit_by_date: dict[pd.Timestamp, dict] = {}
    if audit_df is not None and not audit_df.empty:
        for _, a in audit_df.iterrows():
            d = pd.Timestamp(a["started_at"]).tz_localize(None).normalize()
            outcome, notes = a.get("outcome"), a.get("notes")
            if d in audit_by_date:
                # A two-slot day (13:37 + 14:37 UTC) can have two daily-check
                # invocations; aggregate rather than let the later row
                # silently overwrite an earlier error:* outcome (#403
                # finding 3).
                prev = audit_by_date[d]
                audit_by_date[d] = {
                    "outcome": _join_audit_values(prev["outcome"], outcome),
                    "notes": _join_audit_values(prev["notes"], notes),
                }
            else:
                audit_by_date[d] = {"outcome": outcome, "notes": notes}

    rows = []
    for _, row in regime_state_df.iterrows():
        d = pd.Timestamp(row["date"]).tz_localize(None).normalize()
        pos = sig_index.searchsorted(d, side="left")
        if pos == 0:
            continue  # no prior trading day in the replay index — can't replay this row
        prev_day = sig_index[pos - 1]
        replayed_bool = bool(replayed_signal.loc[prev_day])
        replayed_target = "LONG" if replayed_bool else "CASH"

        spy_close_diff_pct = float("nan")
        spy_sma200_diff_pct = float("nan")
        if benchmark_close is not None and prev_day in benchmark_close.index:
            yf_close = float(benchmark_close.loc[prev_day])
            if yf_close != 0:
                spy_close_diff_pct = (float(row["spy_close"]) - yf_close) / yf_close * 100
            yf_sma = float(sma.loc[prev_day]) if sma is not None and prev_day in sma.index else float("nan")
            if pd.notna(yf_sma) and yf_sma != 0:
                spy_sma200_diff_pct = (float(row["spy_sma200"]) - yf_sma) / yf_sma * 100

        audit_entry = audit_by_date.get(d, {})

        rows.append({
            "date": d,
            "target_state": row["target_state"],
            "current_state": row["current_state"],
            "replayed_target": replayed_target,
            "signal_mismatch": replayed_target != row["target_state"],
            "execution_mismatch": replayed_target != row["current_state"],
            "spy_close_diff_pct": spy_close_diff_pct,
            "spy_sma200_diff_pct": spy_sma200_diff_pct,
            "outcome": audit_entry.get("outcome"),
            "notes": audit_entry.get("notes"),
        })

    return pd.DataFrame(rows)


def run_report(
    *,
    export_dir: str | Path,
    benchmark: str = "SPY",
    vehicle: str = "UPRO",
    sma_days: int = 200,
) -> dict:
    """Orchestrate the full divergence report from an exported live history.

    Window = [earliest, latest] exported equity_snapshots date (D3). Starting
    cash = the earliest snapshot's equity_usd. Simulates from one trading day
    before the window (so the T+1-shifted signal is valid on day 1), then
    Trap-A-slices the equity curve to the window before computing tracking
    error. Tracking is also computed since the first live fill (isolating
    the execution model from the go-live ramp) when there is at least one
    fill and 2+ overlapping snapshot dates in that sub-window.
    """
    data = load_live_export(export_dir)
    equity = data["equity_snapshots"]
    if equity.empty:
        raise ValueError("equity_snapshots export is empty — nothing to compare")

    equity = equity.sort_values("date").reset_index(drop=True)
    window_start = pd.Timestamp(equity["date"].iloc[0])
    window_end = pd.Timestamp(equity["date"].iloc[-1])
    starting_cash = float(equity["equity_usd"].iloc[0])

    fetch_start = (window_start - pd.DateOffset(days=_MAX_LOOKBACK_DAYS * 2)).date()
    fetch_end = (window_end + pd.Timedelta(days=1)).date()

    benchmark_full = _fetch(benchmark, fetch_start, fetch_end)
    vehicle_full = _fetch(vehicle, fetch_start, fetch_end)

    common = benchmark_full.index.intersection(vehicle_full.index)
    benchmark_full = benchmark_full.loc[common]
    vehicle_full = vehicle_full.loc[common]

    signal_full = replay_signal(benchmark_full, sma_days=sma_days)

    # Simulate from one trading day before window_start (Trap-A idiom): the
    # T+1-shifted signal needs a close-T signal already available on day 1.
    ts_pos = common.searchsorted(window_start, side="left")
    pr_pos = max(0, ts_pos - 1)
    sim_start = common[pr_pos]
    sim_mask = (common >= sim_start) & (common <= window_end)

    sim = simulate_from_signal(
        vehicle_df=vehicle_full.loc[sim_mask],
        is_bullish_close_t=signal_full.loc[sim_mask],
        starting_cash=starting_cash,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )
    eq_full = sim["equity_curve"]
    window_mask = (eq_full.index >= window_start) & (eq_full.index <= window_end)
    eq_window = eq_full.loc[window_mask]

    tracking_full = compute_tracking(equity, eq_window, starting_cash=starting_cash)

    trades = data["trades"]
    tracking_since_first_fill = None
    if not trades.empty:
        first_fill_date = pd.Timestamp(trades["fill_time"].iloc[0]).tz_localize(None).normalize()
        eq_since = eq_window.loc[eq_window.index >= first_fill_date]
        equity_since = equity[pd.to_datetime(equity["date"]) >= first_fill_date]
        if len(eq_since) >= 2 and len(equity_since) >= 2:
            tracking_since_first_fill = compute_tracking(equity_since, eq_since)

    fill_slippage = compute_fill_slippage(trades, vehicle_full)

    divergence = compute_divergence_dates(
        data["regime_state"], signal_full, data["audit_log"],
        benchmark_close=benchmark_full["Close"], sma_days=sma_days,
    )

    return {
        "window_start": window_start,
        "window_end": window_end,
        "starting_cash": starting_cash,
        "tracking_full": tracking_full,
        "tracking_since_first_fill": tracking_since_first_fill,
        "fill_slippage": fill_slippage,
        "divergence": divergence,
        "sim_result": sim,
    }


def _print_report(report: dict) -> None:
    print(
        f"Live window: {report['window_start'].date()} -> {report['window_end'].date()}  "
        f"(starting cash ${report['starting_cash']:,.2f})"
    )
    print()

    print("Tracking error (full window):")
    for k, v in report["tracking_full"].items():
        print(f"  {k:<24} {v:.6f}" if isinstance(v, float) else f"  {k:<24} {v}")
    print()

    if report["tracking_since_first_fill"] is not None:
        print("Tracking error (since first live fill):")
        for k, v in report["tracking_since_first_fill"].items():
            print(f"  {k:<24} {v:.6f}" if isinstance(v, float) else f"  {k:<24} {v}")
        print()

    fs = report["fill_slippage"]
    print(f"Fill slippage: {len(fs)} fill(s)")
    if not fs.empty:
        print(fs.to_string(index=False))
    print()

    div = report["divergence"]
    n_signal = int(div["signal_mismatch"].sum()) if not div.empty else 0
    n_exec = int(div["execution_mismatch"].sum()) if not div.empty else 0
    print(f"Divergence dates: {n_signal} signal-parity, {n_exec} execution-parity (of {len(div)} rows)")
    mismatches = div[div["signal_mismatch"] | div["execution_mismatch"]] if not div.empty else div
    if not mismatches.empty:
        print(mismatches.to_string(index=False))
    if not div.empty:
        print(
            f"  max |spy_close diff %|  = {div['spy_close_diff_pct'].abs().max():.4f}"
        )
        print(
            f"  max |spy_sma200 diff %| = {div['spy_sma200_diff_pct'].abs().max():.4f}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Print the divergence report."""
    parser = argparse.ArgumentParser(prog="backtest.run_live_divergence")
    parser.add_argument("--export-dir", default="live_export", help="dir with the exported CSVs")
    parser.add_argument("--benchmark", default="SPY", help="benchmark ticker (default SPY)")
    parser.add_argument("--vehicle", default="UPRO", help="vehicle ticker (default UPRO)")
    parser.add_argument("--sma", type=int, default=200, help="SMA window in days (default 200)")
    args = parser.parse_args(argv)

    report = run_report(
        export_dir=args.export_dir,
        benchmark=args.benchmark,
        vehicle=args.vehicle,
        sma_days=args.sma,
    )
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
