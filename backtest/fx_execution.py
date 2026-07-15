"""Long/short, single-position, fixed-TP/SL 4h bar-loop simulator (#371).

Research-only. Lives in ``backtest/`` and is never imported by
``supabase/functions/``. No LLM, no broker calls, no orders — ``simulate_fx``
is a pure function of a bar history and a signal series.

Shape follows ``backtest/run_scalping_cost_wall.py``'s ``run_backtest``
(the in-repo precedent for a bar-indexed intraday simulator); the existing
``simulate_from_signal`` in ``backtest/regime.py`` is long-only, daily, and
has no TP/SL, so it cannot express these semantics — this is a sibling
simulator, not a duplicate. The returned dict's shape
(``equity_curve``/``trades`` with ``entry_date``/``exit_date``/``pnl``/
``total_return``/``max_drawdown``/``trade_count``) matches
``simulate_from_signal`` so ``backtest/tax.py`` and
``backtest/walkforward._compute_window_metrics`` consume it unchanged.

Locked semantics (batch #370 decision log, mirrored from the #371 SUB_PLAN):
  1. One position at a time — a signal that arrives while already in a trade
     is ignored.
  2. ``entry_dir`` is decided at bar t's CLOSE, values in {+1, -1, 0}.
  3. TP/SL price levels are fixed at entry from ``tp_pct``/``sl_pct`` and
     never move (no trailing).
  4. Fill at bar t+1's OPEN. Stop-first when both TP and SL are touched in
     the same bar. The entry bar's OWN high/low ALSO tests TP/SL (lead
     decision: the fill is at that bar's open, which precedes the bar's own
     extremes in time — skipping this would gift every trade 4h of stop
     immunity). Gap handling: if a bar OPENS beyond a level, fill at the
     open (no gap-through gift, no gap-through rescue); otherwise fill at
     the level itself. The in-progress final bar is dropped upstream, at
     load, by ``fx_data.drop_in_progress_bar`` — not here.
  5. Equity compounds as:
     ``equity *= 1 + dir*(exit/entry - 1) - cost_rt - nights*overnight_dir``
     — i.e. 100% of equity is exposed at 1x, no leverage.

Self-check: every exit's bar-index is >= its entry's bar-index, strictly
greater for a non-entry-bar exit; same-bar (entry-bar) exits are flagged in
the ledger via ``same_bar_exit`` rather than treated as a violation.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def _test_bar_for_exit(
    direction: int, open_px: float, high_px: float, low_px: float,
    tp_level: float, sl_level: float,
) -> Optional[tuple]:
    """Test one bar's OHLC against the entry's fixed TP/SL levels.

    Stop-first when both are touched in the same bar. Gap handling: if the
    bar's OPEN is already beyond a level, fill at the open (no gap-through
    gift/rescue); otherwise fill at the level itself (reached mid-bar). Note
    stop-first applies even when the bar gaps THROUGH the TP level too — SL
    is tested and filled first regardless of which level the open itself has
    already passed, so a bar that gaps past both levels always exits "sl".

    Returns (exit_price, reason) with reason in {"tp", "sl"}, or None if
    neither level is touched this bar.
    """
    if direction == 1:
        sl_hit = low_px <= sl_level
        tp_hit = high_px >= tp_level
        if sl_hit:
            exit_price = open_px if open_px <= sl_level else sl_level
            return exit_price, "sl"
        if tp_hit:
            exit_price = open_px if open_px >= tp_level else tp_level
            return exit_price, "tp"
        return None
    elif direction == -1:
        sl_hit = high_px >= sl_level
        tp_hit = low_px <= tp_level
        if sl_hit:
            exit_price = open_px if open_px >= sl_level else sl_level
            return exit_price, "sl"
        if tp_hit:
            exit_price = open_px if open_px <= tp_level else tp_level
            return exit_price, "tp"
        return None
    else:
        raise ValueError(f"direction must be +1 or -1, got {direction!r}")


def _nights_held(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> int:
    """Calendar nights spanned (incl. weekends) between entry and exit — an
    approximation of the triple-swap-Wednesday convention (see
    ``backtest/fx_costs.py`` docstring for the per-night bp figures this is
    multiplied against)."""
    return int((exit_ts.normalize() - entry_ts.normalize()).days)


def _assert_trade_ordering(entry_idx: int, exit_idx: int, same_bar_exit: bool) -> None:
    """No-look-ahead self-check: the exit bar-index must be >= the entry
    bar-index, strictly greater for anything NOT flagged as a same-bar
    (entry-bar) exit. Directly unit-testable with contrived indices."""
    if same_bar_exit:
        assert exit_idx == entry_idx, (
            f"same_bar_exit=True but exit bar {exit_idx} != entry bar {entry_idx}"
        )
    else:
        assert exit_idx > entry_idx, (
            f"exit bar {exit_idx} must be strictly after entry bar {entry_idx} "
            "for a non-entry-bar exit (no look-ahead)"
        )


def _close_trade(
    *, entry_ts: pd.Timestamp, exit_ts: pd.Timestamp, direction: int,
    entry_price: float, exit_price: float, reason: str, same_bar_exit: bool,
    cost_rt: float, overnight: Optional[dict], equity_before: float,
) -> dict:
    gross_ret = direction * (exit_price / entry_price - 1.0)
    nights = _nights_held(entry_ts, exit_ts)
    overnight_cost = 0.0
    if overnight is not None:
        overnight_cost = nights * overnight.get(direction, 0.0)
    net_ret = gross_ret - cost_rt - overnight_cost
    pnl = equity_before * net_ret
    return {
        "entry_date": entry_ts,
        "exit_date": exit_ts,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "return_pct": net_ret,
        "exit_reason": reason,
        "same_bar_exit": same_bar_exit,
        "nights_held": nights,
    }


def simulate_fx(
    bars_4h: pd.DataFrame,
    entry_dir: pd.Series,
    *,
    tp_pct: float,
    sl_pct: float,
    cost_rt: float,
    overnight: Optional[dict] = None,
    starting_equity: float = 100_000.0,
) -> dict:
    """Single-position long/short bar loop with fixed TP/SL.

    Parameters
    ----------
    bars_4h:
        DataFrame with ``Open``/``High``/``Low``/``Close`` columns (mid
        prices — the signal-price convention is the caller's choice via
        ``entry_dir``; fills/costs are on these same OHLC columns). The
        in-progress final bar must already be dropped by the caller.
    entry_dir:
        Series aligned to ``bars_4h.index``, values in {-1, 0, 1} — the
        signal DECIDED AT bar t's close. This function applies the T -> T+1
        fill shift ITSELF (reads ``entry_dir`` at bar i-1 to decide entry at
        bar i) — do not pre-shift the input.
    tp_pct, sl_pct:
        Fractional distance from the entry price (e.g. 0.003 = 30bp).
    cost_rt:
        Round-trip cost, a fraction of notional (e.g. 0.000104 = 1.04bp).
        Positive = cost, charged once per closed trade.
    overnight:
        ``None`` (no daily rollover charge — the futures convention), or a
        ``{1: rate_long, -1: rate_short}`` dict of per-night fractional
        costs (positive = cost; see ``fx_costs.overnight_bp_for``).
    starting_equity:
        Initial capital.

    Returns
    -------
    dict with keys ``equity_curve`` (pd.Series), ``trades`` (list of dicts:
    ``entry_date``, ``exit_date``, ``direction``, ``entry_price``,
    ``exit_price``, ``pnl``, ``return_pct``, ``exit_reason``,
    ``same_bar_exit``, ``nights_held``), ``total_return``, ``max_drawdown``,
    ``trade_count`` — the same shape ``simulate_from_signal`` returns.
    """
    idx = bars_4h.index
    opens = bars_4h["Open"].to_numpy(dtype=float)
    highs = bars_4h["High"].to_numpy(dtype=float)
    lows = bars_4h["Low"].to_numpy(dtype=float)
    closes = bars_4h["Close"].to_numpy(dtype=float)
    sig = entry_dir.reindex(idx).fillna(0).astype(int).to_numpy()
    n = len(bars_4h)

    trades: list = []
    equity = float(starting_equity)
    equity_at_entry = equity
    eq_curve: list = []

    in_pos = False
    direction = 0
    entry_price = 0.0
    entry_ts: Optional[pd.Timestamp] = None
    entry_idx = -1
    tp_level = 0.0
    sl_level = 0.0

    i = 0
    while i < n:
        ts = idx[i]
        if not in_pos:
            prev_dir = int(sig[i - 1]) if i >= 1 else 0
            if prev_dir != 0:
                in_pos = True
                direction = prev_dir
                entry_price = float(opens[i])
                entry_ts = ts
                entry_idx = i
                equity_at_entry = equity
                if direction == 1:
                    tp_level = entry_price * (1.0 + tp_pct)
                    sl_level = entry_price * (1.0 - sl_pct)
                else:
                    tp_level = entry_price * (1.0 - tp_pct)
                    sl_level = entry_price * (1.0 + sl_pct)

                # Entry bar's own high/low also tests TP/SL (lead decision):
                # the fill is at this bar's OPEN, so its extremes occur
                # after entry in time.
                exit_info = _test_bar_for_exit(
                    direction, opens[i], highs[i], lows[i], tp_level, sl_level
                )
                if exit_info is not None:
                    exit_price, reason = exit_info
                    _assert_trade_ordering(entry_idx, i, same_bar_exit=True)
                    trade = _close_trade(
                        entry_ts=entry_ts, exit_ts=ts, direction=direction,
                        entry_price=entry_price, exit_price=exit_price,
                        reason=reason, same_bar_exit=True,
                        cost_rt=cost_rt, overnight=overnight,
                        equity_before=equity_at_entry,
                    )
                    trades.append(trade)
                    equity = equity_at_entry + trade["pnl"]
                    in_pos = False
            eq_curve.append((ts, equity))
            i += 1
            continue

        # Already in a position (opened on an earlier bar) — test this bar.
        exit_info = _test_bar_for_exit(direction, opens[i], highs[i], lows[i], tp_level, sl_level)
        if exit_info is not None:
            exit_price, reason = exit_info
            _assert_trade_ordering(entry_idx, i, same_bar_exit=False)
            trade = _close_trade(
                entry_ts=entry_ts, exit_ts=ts, direction=direction,
                entry_price=entry_price, exit_price=exit_price,
                reason=reason, same_bar_exit=False,
                cost_rt=cost_rt, overnight=overnight,
                equity_before=equity_at_entry,
            )
            trades.append(trade)
            equity = equity_at_entry + trade["pnl"]
            in_pos = False
            eq_curve.append((ts, equity))
            i += 1
            continue

        # No exit this bar: mark equity to this bar's close (unrealized).
        unreal_ret = direction * (float(closes[i]) / entry_price - 1.0)
        eq_curve.append((ts, equity_at_entry * (1.0 + unreal_ret)))
        i += 1

    # Close any still-open position at the final bar's close.
    if in_pos:
        ts = idx[-1]
        exit_price = float(closes[-1])
        same_bar = (n - 1) == entry_idx
        trade = _close_trade(
            entry_ts=entry_ts, exit_ts=ts, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            reason="end_of_window", same_bar_exit=same_bar,
            cost_rt=cost_rt, overnight=overnight,
            equity_before=equity_at_entry,
        )
        trades.append(trade)
        equity = equity_at_entry + trade["pnl"]
        if eq_curve:
            eq_curve[-1] = (eq_curve[-1][0], equity)

    eq_series = pd.Series(dict(eq_curve))
    eq_series.index.name = "datetime_utc"
    total_return = float(eq_series.iloc[-1] / starting_equity - 1.0) if len(eq_series) else 0.0
    if len(eq_series):
        rolling_max = eq_series.cummax()
        max_dd = float(((eq_series - rolling_max) / rolling_max).min())
    else:
        max_dd = 0.0

    return {
        "equity_curve": eq_series,
        "trades": trades,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
    }


def simulate_fx_state(
    bars_4h: pd.DataFrame,
    state: pd.Series,
    *,
    cost_rt: float,
    overnight: Optional[dict] = None,
    starting_equity: float = 100_000.0,
) -> dict:
    """State-based long/short sibling of ``simulate_fx`` (#376, SUB_PLAN §3),
    with NO TP/SL bracket -- exits only on a state flip or a forced
    window-end close. Used for baselines 3 (persistence) and 4 (200-SMA
    regime), which have no natural TP/SL of their own (spec §5: "Baselines
    are state-based ... not run through the same TP/SL execution layer").

    Locked semantics (derived from §1, mirrored from ``simulate_fx``):
      - ``state`` is decided AT bar t's close, values in {-1, 0, 1}. This
        function applies the T -> T+1 fill shift ITSELF (reads ``state`` at
        bar i-1 to decide the position held from bar i) -- do not pre-shift.
      - A flip (state changes to a different, possibly zero, value) CLOSES
        the old position and, if the new state is non-zero, OPENS the new
        one at that SAME bar's open (one flip = at most one closed trade +
        one newly opened trade, both priced off the identical open).
      - One ``cost_rt`` charged per CLOSED trade (same convention as
        ``simulate_fx``).
      - Overnight financing via the existing ``_nights_held``/``overnight``
        dict, applied identically to ``simulate_fx``.
      - Forced close at the final bar's CLOSE if a position is still open
        when the window ends.

    Returns the same dict shape as ``simulate_fx`` (``equity_curve``,
    ``trades``, ``total_return``, ``max_drawdown``, ``trade_count``) so
    ``tax.py`` and the metrics code consume it unchanged.
    """
    idx = bars_4h.index
    opens = bars_4h["Open"].to_numpy(dtype=float)
    closes = bars_4h["Close"].to_numpy(dtype=float)
    sig = state.reindex(idx).fillna(0).astype(int).to_numpy()
    n = len(bars_4h)

    trades: list = []
    equity = float(starting_equity)
    equity_at_entry = equity
    eq_curve: list = []

    in_pos = False
    direction = 0
    entry_price = 0.0
    entry_ts: Optional[pd.Timestamp] = None
    entry_idx = -1

    i = 0
    while i < n:
        ts = idx[i]
        desired = int(sig[i - 1]) if i >= 1 else 0

        if not in_pos:
            if desired != 0:
                in_pos = True
                direction = desired
                entry_price = float(opens[i])
                entry_ts = ts
                entry_idx = i
                equity_at_entry = equity
                # Entry-bar equity-curve convention matches ``simulate_fx``
                # exactly: the point at the bar that OPENS a position (with
                # no same-bar exit) is the PRE-entry equity, not a
                # same-bar mark-to-market against this bar's own close.
                # Mark-to-market starts from the NEXT bar's "already in a
                # position" branch below. Aligned deliberately -- the two
                # sibling simulators must agree here, or max-drawdown
                # detection would be biased differently between candidate
                # cells (``simulate_fx``) and baselines (this function).
            eq_curve.append((ts, equity))
            i += 1
            continue

        if desired != direction:
            # State flip (or flat): close the open position at this bar's
            # open -- the fill mechanics are identical for "flip to
            # opposite" and "flip to flat" (only the reason label differs).
            exit_price = float(opens[i])
            same_bar_exit = (i == entry_idx)
            _assert_trade_ordering(entry_idx, i, same_bar_exit=same_bar_exit)
            trade = _close_trade(
                entry_ts=entry_ts, exit_ts=ts, direction=direction,
                entry_price=entry_price, exit_price=exit_price,
                reason=("state_flip" if desired != 0 else "state_flat"),
                same_bar_exit=same_bar_exit,
                cost_rt=cost_rt, overnight=overnight, equity_before=equity_at_entry,
            )
            trades.append(trade)
            equity = equity_at_entry + trade["pnl"]
            in_pos = False

            if desired != 0:
                # Reopen immediately at the SAME open (the flip's one fill).
                direction = desired
                entry_price = exit_price
                entry_ts = ts
                entry_idx = i
                equity_at_entry = equity
                in_pos = True
                unreal_ret = direction * (float(closes[i]) / entry_price - 1.0)
                eq_curve.append((ts, equity_at_entry * (1.0 + unreal_ret)))
            else:
                eq_curve.append((ts, equity))
            i += 1
            continue

        # Holding, state unchanged -> mark to market at this bar's close.
        unreal_ret = direction * (float(closes[i]) / entry_price - 1.0)
        eq_curve.append((ts, equity_at_entry * (1.0 + unreal_ret)))
        i += 1

    # Force-close any still-open position at the final bar's close.
    if in_pos:
        ts = idx[-1]
        exit_price = float(closes[-1])
        same_bar = (n - 1) == entry_idx
        trade = _close_trade(
            entry_ts=entry_ts, exit_ts=ts, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            reason="end_of_window", same_bar_exit=same_bar,
            cost_rt=cost_rt, overnight=overnight, equity_before=equity_at_entry,
        )
        trades.append(trade)
        equity = equity_at_entry + trade["pnl"]
        if eq_curve:
            eq_curve[-1] = (eq_curve[-1][0], equity)

    eq_series = pd.Series(dict(eq_curve))
    eq_series.index.name = "datetime_utc"
    total_return = float(eq_series.iloc[-1] / starting_equity - 1.0) if len(eq_series) else 0.0
    if len(eq_series):
        rolling_max = eq_series.cummax()
        max_dd = float(((eq_series - rolling_max) / rolling_max).min())
    else:
        max_dd = 0.0

    return {
        "equity_curve": eq_series,
        "trades": trades,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
    }


def equity_to_daily(equity_curve: pd.Series) -> pd.Series:
    """Last mark per UTC calendar day, so daily-convention metrics (Sharpe,
    ``walkforward._compute_window_metrics``) can consume a 4h-cadence curve."""
    daily = equity_curve.groupby(equity_curve.index.normalize()).last()
    daily.index.name = "date"
    return daily
