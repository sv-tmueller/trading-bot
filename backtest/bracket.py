"""Reusable intra-bar BRACKET backtest engine (#430, P1 of #429).

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
No LLM, no broker calls, no broker-client import.

Why a new engine? ``backtest.regime.simulate_from_signal`` has no intra-bar
High/Low exit (it drops High/Low entirely), and ``run_scalping_cost_wall.py`` has
intra-bar stops but no fixed target, no tie-break, and optimistic gap fills — and
it is a pinned #311 reproducibility artifact that must stay byte-identical. So this
module is a minimal NEW simulator that *reuses the scalping engine's conventions as
a reference* while producing a trade ledger whose dict shape matches
``simulate_from_signal`` so the after-tax layer (``tax.apply_tax_to_ledger``) and the
survey metrics (``run_candidate_survey._after_tax_metrics``) consume it unchanged.

The critical reuse property (so #431's ORB can reuse this with no rework):
``simulate_bracket`` takes **per-entry ABSOLUTE stop/target price levels computed by
the caller** — it never hardcodes ``entry ± kN`` internally. Turtle passes
``entry − 2N`` / ``entry + R·N``; ORB will pass the OR opposite side / a measured move.

Frozen fill / tie-break / gap conventions (long-only v1) — see
docs/research/2026-07-24-turtle-breakout-verdict.md. Exit tests run STRICTLY AFTER the
entry bar (the entry bar is never tested for an exit):
  1. Open-gap first: ``open ≤ stop`` → STOP filled at ``open`` (adverse gap, no gift);
     ``open ≥ target`` → TARGET filled at ``target`` (D3 conservative cap).
  2. Intra-bar: ``low ≤ stop AND high ≥ target`` → STOP-first (conservative tie-break);
     else stop-hit → stop; target-hit → target; else carry (mark to close).
  3. EOW close-out: a position still open at the last bar of an ISO week (and not the
     final bar of the series) is flattened at that bar's close (``exit_reason="eow"``);
     the final bar flattens at its close (``exit_reason="end_of_window"``). The additive
     ``session_close_out`` mode (default off, #431 ORB) does the same at each calendar
     date's last bar (``exit_reason="session"``) — checked before EOW, after a natural
     stop/target exit.
  4. No look-ahead; every trade satisfies ``exit_date > entry_date``.
  5. Cost model: entry at ``open·(1+slip)`` with a ``(1+comm)`` haircut; every exit at
     ``fill_level·(1−slip)`` with a ``(1−comm)`` haircut (the ``regime.py`` constants).
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, STARTING_CASH


def donchian_breakout_signal(
    high: pd.Series, close: pd.Series, window: int = 55
) -> pd.Series:
    """Donchian ``window``-bar breakout, no look-ahead.

    ``close > high.shift(1).rolling(window).max()`` — the rolling max is taken over
    the ``window`` bars strictly BEFORE the signal bar (``shift(1)`` drops the current
    bar's own high), so the breakout is confirmed only against completed prior bars.
    NaN during warm-up compares False. Strict ``>`` (an equal touch is not a breakout).
    Returns a boolean Series aligned to ``close`` (the close-t signal; the caller shifts
    it by one bar to fill at the next open).
    """
    prior_high = high.shift(1).rolling(window).max()
    return (close > prior_high).fillna(False)


def _resolve_bar(
    open_: float,
    high: float,
    low: float,
    stop: float,
    target: Optional[float],
) -> Optional[Tuple[float, str]]:
    """Resolve one post-entry bar to an exit ``(fill_level, reason)`` or ``None`` (carry).

    Pure price logic (no costs). ``target`` may be ``None`` (pure-stop bracket). Encodes
    the frozen conventions: open-gap first, then STOP-first intra-bar tie-break.
    """
    # 1. Open-gap first (an adverse/favorable gap is resolved at the open).
    if open_ <= stop:
        return (open_, "stop")           # gapped through the stop: fill at open, no gift
    if target is not None and open_ >= target:
        return (target, "target")        # gapped above the target: cap at target (D3)

    # 2. Intra-bar: open is inside the bracket.
    hit_stop = low <= stop
    hit_target = target is not None and high >= target
    if hit_stop and hit_target:
        return (stop, "stop")            # conservative STOP-first tie-break
    if hit_stop:
        return (stop, "stop")
    if hit_target:
        return (target, "target")
    return None                          # neither touched: carry


def _session_end_flags(index: pd.DatetimeIndex) -> np.ndarray:
    """True where a bar is the last bar of its calendar date within ``index``.

    The intraday analogue of ``_week_end_flags`` (#431 ORB reuse): a US session lives
    inside one UTC date (open 13:30/14:30 → close 20:00/21:00 UTC), so grouping by the
    normalized timestamp is grouping by session. The final bar is also flagged, but the
    loop handles it separately as ``end_of_window``.
    """
    keys = index.normalize().to_numpy()
    n = len(index)
    flags = np.zeros(n, dtype=bool)
    for i in range(n):
        if i == n - 1 or keys[i] != keys[i + 1]:
            flags[i] = True
    return flags


def _week_end_flags(index: pd.DatetimeIndex) -> np.ndarray:
    """True where a bar is the last bar of its ISO (year, week) within ``index``.

    The final bar is also flagged (it ends its week within the series), but the loop
    handles the final bar separately as ``end_of_window``.
    """
    iso = index.isocalendar()
    keys = list(zip(iso["year"].to_numpy(), iso["week"].to_numpy()))
    n = len(index)
    flags = np.zeros(n, dtype=bool)
    for i in range(n):
        if i == n - 1 or keys[i] != keys[i + 1]:
            flags[i] = True
    return flags


def simulate_bracket(
    df: pd.DataFrame,
    entry_trigger: pd.Series,
    stop_prices: pd.Series,
    target_prices: Optional[pd.Series] = None,
    *,
    starting_cash: float = STARTING_CASH,
    slippage_bps: int = SLIPPAGE_BPS,
    commission_bps: int = COMMISSION_BPS,
    eow_close_out: bool = True,
    session_close_out: bool = False,
) -> dict:
    """Long-only single-lot bracket simulation over an OHLC frame.

    Parameters
    ----------
    df:
        OHLC DataFrame with ``Open``/``High``/``Low``/``Close`` columns, indexed by
        trading date/timestamp (sorted, unique).
    entry_trigger:
        Boolean Series aligned to ``df.index``. ``True`` at a bar means **enter at that
        bar's open** — the caller has already applied the close-t → next-open shift
        (typically ``signal.shift(1)``). While a lot is open, further triggers are
        ignored (long-only, no pyramiding).
    stop_prices:
        Absolute stop price to use for an entry, aligned to ``df.index``, read at the
        entry bar. NaN at a triggered bar suppresses that entry.
    target_prices:
        Absolute target price, aligned to ``df.index``, read at the entry bar. Pass
        ``None`` for a pure-stop bracket; a NaN value for a particular entry likewise
        means "no target for that lot". **Never** ``entry ± kN`` computed here — the
        caller owns the geometry (this is what lets #431's ORB reuse this engine).
    starting_cash, slippage_bps, commission_bps:
        Cost model (the ``regime.py`` constants by default).
    eow_close_out:
        When True (default), flatten any lot still open at the last bar of an ISO week.
    session_close_out:
        When True (default False), flatten any lot still open at the last bar of its
        calendar date (``exit_reason="session"``) — the intraday EOD-flat mode #431's ORB
        uses (never hold overnight). Additive and independent of ``eow_close_out``; a
        natural stop/target exit still takes priority on the same bar.

    Returns
    -------
    dict with the same keys as ``simulate_from_signal``: ``total_return``,
    ``max_drawdown``, ``trade_count``, ``ending_equity``, ``starting_cash``,
    ``trades`` (list of dicts with entry_date/exit_date/entry_price/exit_price/qty/
    pnl/return_pct/exit_reason), ``equity_curve`` (pd.Series marked to close).
    """
    index = df.index
    n = len(index)
    opens = df["Open"].to_numpy(dtype=float)
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)

    trig = entry_trigger.reindex(index).fillna(False).to_numpy(dtype=bool)
    stops = stop_prices.reindex(index).to_numpy(dtype=float)
    if target_prices is None:
        targets = None
    else:
        targets = target_prices.reindex(index).to_numpy(dtype=float)

    week_end = _week_end_flags(index) if eow_close_out else np.zeros(n, dtype=bool)
    session_end = (
        _session_end_flags(index) if session_close_out else np.zeros(n, dtype=bool)
    )

    slip = slippage_bps / 10_000.0
    comm = commission_bps / 10_000.0

    cash = float(starting_cash)
    qty = 0
    entry_price = 0.0
    entry_date = None
    cur_stop = 0.0
    cur_target: Optional[float] = None
    trades: list[dict] = []
    equity_curve: list[tuple] = []

    def _close(fill_level: float, reason: str, ts) -> None:
        nonlocal cash, qty, entry_price, entry_date, cur_stop, cur_target
        exec_px = fill_level * (1 - slip)
        proceeds = qty * exec_px * (1 - comm)
        pnl = proceeds - qty * entry_price * (1 + comm)
        cash += proceeds
        trades.append({
            "entry_date": entry_date,
            "exit_date": ts,
            "entry_price": entry_price,
            "exit_price": exec_px,
            "qty": qty,
            "pnl": pnl,
            "return_pct": exec_px / entry_price - 1.0,
            "exit_reason": reason,
        })
        qty = 0
        entry_price = 0.0
        entry_date = None
        cur_stop = 0.0
        cur_target = None

    for i, ts in enumerate(index):
        if qty == 0:
            # Flat: consider entering at THIS bar's open. The entry bar is never
            # tested for an exit — we mark to close and move on. Never enter on the
            # final bar: there is no subsequent bar to ever exit on, and a same-bar
            # forced close-out would violate exit_date > entry_date.
            if trig[i] and i != n - 1 and not np.isnan(stops[i]):
                exec_px = opens[i] * (1 + slip)
                size = int(cash / exec_px / (1 + comm)) if exec_px > 0 else 0
                if size > 0:
                    qty = size
                    cash -= qty * exec_px * (1 + comm)
                    entry_price = exec_px
                    entry_date = ts
                    cur_stop = stops[i]
                    cur_target = (
                        None if targets is None or np.isnan(targets[i]) else targets[i]
                    )
            equity_curve.append((ts, cash + qty * closes[i]))
            continue

        # In a position on a bar strictly after the entry bar.
        res = _resolve_bar(opens[i], highs[i], lows[i], cur_stop, cur_target)
        if res is not None:
            _close(res[0], res[1], ts)
            equity_curve.append((ts, cash))
            continue

        if session_end[i] and i != n - 1:
            _close(closes[i], "session", ts)
            equity_curve.append((ts, cash))
            continue

        if week_end[i] and i != n - 1:
            _close(closes[i], "eow", ts)
            equity_curve.append((ts, cash))
            continue

        equity_curve.append((ts, cash + qty * closes[i]))

    # Close any lot still open at the final bar's close.
    if qty > 0:
        last_ts = index[-1]
        _close(closes[-1], "end_of_window", last_ts)
        equity_curve[-1] = (last_ts, cash)

    for t in trades:
        assert t["exit_date"] > t["entry_date"], (
            f"exit {t['exit_date']} not after entry {t['entry_date']}"
        )

    eq_series = pd.Series(dict(equity_curve))
    total_return = float(eq_series.iloc[-1] / starting_cash - 1.0)
    rolling_max = eq_series.cummax()
    max_dd = float(((eq_series - rolling_max) / rolling_max).min())

    return {
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "ending_equity": float(eq_series.iloc[-1]),
        "starting_cash": starting_cash,
        "trades": trades,
        "equity_curve": eq_series,
    }
