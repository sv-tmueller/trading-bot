"""Tests for backtest/fx_execution.py — long/short fixed-TP/SL 4h bar-loop
simulator (#371).

Hand-built tiny 4h bar sequences, each proving one locked semantic (batch
#370 decision log): next-open fill, fixed TP/SL (no trailing), stop-first
on a same-bar double-touch, entry-bar TP/SL testing, gap-open fills at the
open, one-position-at-a-time, long AND short, end-of-window close-out,
costs-off == gross, per-direction overnight financing, and the no-look-ahead
self-check. All offline / synthetic — no network, no broker.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest import fx_execution as fx


def _bars(rows: list, start: str = "2024-01-08 00:00", freq: str = "4h") -> pd.DataFrame:
    """rows: list of (open, high, low, close) tuples -> a 4h-indexed OHLC df."""
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    idx.name = "datetime_utc"
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


def _sig(bars: pd.DataFrame, values: list) -> pd.Series:
    return pd.Series(values, index=bars.index)


# ---------------------------------------------------------------------------
# Next-open fill (no look-ahead)
# ---------------------------------------------------------------------------

def test_entry_fills_at_next_bar_open_not_signal_bar_close():
    bars = _bars([
        (1.1000, 1.1005, 1.0995, 1.1002),  # signal bar (long @ close)
        (1.1010, 1.1050, 1.1005, 1.1020),  # entry bar: fill at open=1.1010
        (1.1020, 1.1025, 1.1015, 1.1018),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.05, sl_pct=0.05, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["entry_price"] == pytest.approx(1.1010)
    assert t["entry_date"] == bars.index[1]


# ---------------------------------------------------------------------------
# Fixed TP / SL, no trailing
# ---------------------------------------------------------------------------

def test_fixed_tp_hit_long():
    entry = 1.1000
    tp_pct = 0.01  # TP = 1.1110
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),  # signal bar
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar (fill @ open=entry)
        (entry, entry * 1.02, entry - 0.0005, entry * 1.015),  # TP touched
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=0.05, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["exit_reason"] == "tp"
    assert t["exit_price"] == pytest.approx(entry * (1 + tp_pct))
    assert t["exit_date"] == bars.index[2]


def test_fixed_sl_hit_long():
    entry = 1.1000
    sl_pct = 0.01  # SL = 1.0890
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0002, entry * 0.985, entry * 0.99),  # SL touched
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.05, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_reason"] == "sl"
    assert t["exit_price"] == pytest.approx(entry * (1 - sl_pct))


def test_tp_sl_never_move_no_trailing():
    """A bar that runs favorably without hitting TP must not ratchet the
    stop/TP levels -- the position stays open at the ORIGINAL fixed levels."""
    entry = 1.1000
    tp_pct, sl_pct = 0.02, 0.02
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar
        (entry, entry * 1.015, entry * 0.999, entry * 1.012),  # runs up, no TP touch
        (entry, entry * 1.005, entry * 0.978, entry * 0.999),  # SL should still be at original level
    ])
    sig = _sig(bars, [1, 0, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_reason"] == "sl"
    assert t["exit_price"] == pytest.approx(entry * (1 - sl_pct))
    assert t["exit_date"] == bars.index[3]


# ---------------------------------------------------------------------------
# Stop-first when both TP and SL are touched in one bar
# ---------------------------------------------------------------------------

def test_stop_first_when_both_touched_same_bar_long():
    entry = 1.1000
    tp_pct, sl_pct = 0.01, 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        # high >= TP AND low <= SL in the same bar
        (entry, entry * 1.02, entry * 0.98, entry),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_reason"] == "sl"


def test_stop_first_when_both_touched_same_bar_short():
    entry = 1.1000
    tp_pct, sl_pct = 0.01, 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.02, entry * 0.98, entry),
    ])
    sig = _sig(bars, [-1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_reason"] == "sl"


# ---------------------------------------------------------------------------
# Long AND short
# ---------------------------------------------------------------------------

def test_short_direction_profits_on_price_decline():
    entry = 1.1000
    tp_pct = 0.01  # short TP = price falls to entry*(1-tp_pct)
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0002, entry * 0.985, entry * 0.99),  # price falls -> short TP
    ])
    sig = _sig(bars, [-1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=0.05, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["direction"] == -1
    assert t["exit_reason"] == "tp"
    assert t["pnl"] > 0
    assert t["exit_price"] == pytest.approx(entry * (1 - tp_pct))


# ---------------------------------------------------------------------------
# One position at a time — overlapping signals ignored while in a trade
# ---------------------------------------------------------------------------

def test_one_position_at_a_time_ignores_signal_while_in_trade():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),  # signal: long
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar
        (entry, entry + 0.0005, entry - 0.0005, entry),  # a NEW short signal here should be ignored
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.05, entry - 0.0005, entry * 1.04),  # TP hit, long
    ])
    sig = _sig(bars, [1, -1, 0, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.03, sl_pct=0.05, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    assert result["trades"][0]["direction"] == 1


# ---------------------------------------------------------------------------
# Entry-bar TP/SL testing (lead decision, batch #370)
# ---------------------------------------------------------------------------

def test_entry_bar_own_high_low_can_trigger_tp():
    entry = 1.1000
    tp_pct = 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),  # signal bar
        # entry bar: opens at `entry`, but its OWN high already reaches TP
        (entry, entry * 1.02, entry * 0.999, entry * 1.015),
    ])
    sig = _sig(bars, [1, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=0.05, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["exit_reason"] == "tp"
    assert t["same_bar_exit"] is True
    assert t["entry_date"] == t["exit_date"] == bars.index[1]


# ---------------------------------------------------------------------------
# Gap handling — bar OPENS beyond a level -> fill at the open
# ---------------------------------------------------------------------------

def test_gap_open_beyond_sl_fills_at_open_not_level_long():
    entry = 1.1000
    sl_pct = 0.01  # SL level = entry*(1-0.01) = 1.0890
    gap_open = entry * 0.97  # opens well below the SL level
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar
        (gap_open, gap_open + 0.0002, gap_open - 0.0005, gap_open),  # gapped down through SL
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.05, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_reason"] == "sl"
    # Fills at the gapped OPEN, not the (better, unreachable) SL level.
    assert t["exit_price"] == pytest.approx(gap_open)


def test_no_gap_fills_at_level_not_open_long():
    """When the bar's open is inside the SL/TP band, the fill is at the
    LEVEL itself (the level is reached mid-bar), not the open price."""
    entry = 1.1000
    sl_pct = 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        # open is normal (inside the band); low dips through SL mid-bar
        (entry, entry + 0.0002, entry * 0.985, entry * 0.99),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.05, sl_pct=sl_pct, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    assert t["exit_price"] == pytest.approx(entry * (1 - sl_pct))


# ---------------------------------------------------------------------------
# End-of-window close-out
# ---------------------------------------------------------------------------

def test_end_of_window_closes_open_position_at_last_close():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar
        (entry, entry + 0.0005, entry - 0.0005, entry * 1.001),  # never hits TP/SL
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.05, sl_pct=0.05, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["exit_reason"] == "end_of_window"
    assert t["exit_price"] == pytest.approx(entry * 1.001)
    assert t["exit_date"] == bars.index[-1]


# ---------------------------------------------------------------------------
# Costs-off equals gross
# ---------------------------------------------------------------------------

def test_costs_off_equals_gross_return():
    entry = 1.1000
    tp_pct = 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.02, entry - 0.0005, entry * 1.015),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=0.05, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    gross = (t["exit_price"] / t["entry_price"] - 1.0)
    assert t["return_pct"] == pytest.approx(gross)


def test_cost_rt_reduces_net_return():
    entry = 1.1000
    tp_pct = 0.01
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.02, entry - 0.0005, entry * 1.015),
    ])
    sig = _sig(bars, [1, 0, 0])
    cost_rt = 0.0001  # 1bp
    result = fx.simulate_fx(bars, sig, tp_pct=tp_pct, sl_pct=0.05, cost_rt=cost_rt, overnight=None)
    t = result["trades"][0]
    gross = (t["exit_price"] / t["entry_price"] - 1.0)
    assert t["return_pct"] == pytest.approx(gross - cost_rt)


# ---------------------------------------------------------------------------
# Per-direction overnight financing, per night held
# ---------------------------------------------------------------------------

def test_overnight_financing_charged_per_night_held():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar, day 1
        (entry, entry + 0.0005, entry - 0.0005, entry),  # day 2
        (entry, entry + 0.0005, entry - 0.0005, entry),  # day 3 (still 4h bars but different date)
    ], start="2024-01-08 20:00", freq="24h")  # each bar 1 calendar day apart
    sig = _sig(bars, [1, 0, 0, 0])
    overnight = {1: 0.0001, -1: 0.00005}  # long costs 1bp/night
    result = fx.simulate_fx(
        bars, sig, tp_pct=0.5, sl_pct=0.5, cost_rt=0.0, overnight=overnight,
    )
    t = result["trades"][0]
    nights = (t["exit_date"].normalize() - t["entry_date"].normalize()).days
    assert nights >= 1
    gross = (t["exit_price"] / t["entry_price"] - 1.0)
    expected_net = gross - nights * overnight[1]
    assert t["return_pct"] == pytest.approx(expected_net)


def test_overnight_none_means_no_financing_charge():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
    ], start="2024-01-08 20:00", freq="24h")
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.5, sl_pct=0.5, cost_rt=0.0, overnight=None)
    t = result["trades"][0]
    gross = (t["exit_price"] / t["entry_price"] - 1.0)
    assert t["return_pct"] == pytest.approx(gross)


# ---------------------------------------------------------------------------
# Equity curve / aggregate shape (matches simulate_from_signal's contract)
# ---------------------------------------------------------------------------

def test_result_dict_has_simulate_from_signal_compatible_shape():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.02, entry - 0.0005, entry * 1.015),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.01, sl_pct=0.05, cost_rt=0.0, overnight=None)
    for key in ("equity_curve", "trades", "total_return", "max_drawdown", "trade_count"):
        assert key in result
    assert isinstance(result["equity_curve"], pd.Series)
    for key in ("entry_date", "exit_date", "pnl"):
        assert key in result["trades"][0]


def test_equity_starts_at_starting_equity_and_compounds():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.02, entry - 0.0005, entry * 1.015),
    ])
    sig = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx(
        bars, sig, tp_pct=0.01, sl_pct=0.05, cost_rt=0.0, overnight=None, starting_equity=50_000.0,
    )
    t = result["trades"][0]
    expected_final = 50_000.0 * (1.0 + t["return_pct"])
    assert result["equity_curve"].iloc[-1] == pytest.approx(expected_final)


def test_no_signal_ever_produces_zero_trades():
    bars = _bars([(1.1, 1.1005, 1.0995, 1.1)] * 4)
    sig = _sig(bars, [0, 0, 0, 0])
    result = fx.simulate_fx(bars, sig, tp_pct=0.01, sl_pct=0.01, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 0
    assert result["total_return"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# equity_to_daily helper
# ---------------------------------------------------------------------------

def test_equity_to_daily_takes_last_mark_per_day():
    idx = pd.DatetimeIndex(
        ["2024-01-08 00:00", "2024-01-08 04:00", "2024-01-09 00:00"], tz="UTC"
    )
    eq = pd.Series([100.0, 105.0, 110.0], index=idx)
    daily = fx.equity_to_daily(eq)
    assert len(daily) == 2
    assert daily.iloc[0] == pytest.approx(105.0)
    assert daily.iloc[1] == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# No-look-ahead self-check — raises on a constructed violation
# ---------------------------------------------------------------------------

def test_self_check_raises_on_non_entry_bar_exit_not_strictly_after_entry():
    with pytest.raises(AssertionError):
        fx._assert_trade_ordering(entry_idx=3, exit_idx=3, same_bar_exit=False)


def test_self_check_raises_on_exit_before_entry():
    with pytest.raises(AssertionError):
        fx._assert_trade_ordering(entry_idx=3, exit_idx=2, same_bar_exit=False)


def test_self_check_raises_when_same_bar_flag_mismatches_indices():
    with pytest.raises(AssertionError):
        fx._assert_trade_ordering(entry_idx=3, exit_idx=4, same_bar_exit=True)


def test_self_check_passes_on_valid_same_bar_exit():
    fx._assert_trade_ordering(entry_idx=3, exit_idx=3, same_bar_exit=True)


def test_self_check_passes_on_valid_later_bar_exit():
    fx._assert_trade_ordering(entry_idx=3, exit_idx=5, same_bar_exit=False)


# ---------------------------------------------------------------------------
# simulate_fx_state (#376) -- state-based long/short sibling, no TP/SL:
# exits only on state flip or window end.
# ---------------------------------------------------------------------------

def test_state_entry_fills_at_next_bar_open_not_decision_bar_close():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),  # state decided here: +1
        (entry + 0.001, entry + 0.002, entry, entry + 0.0015),  # fill AT this bar's open
        (entry + 0.001, entry + 0.002, entry, entry + 0.0015),  # decided state=0 last bar -> close here
    ])
    state = _sig(bars, [1, 0, 0])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["entry_price"] == pytest.approx(entry + 0.001)
    assert t["entry_date"] == bars.index[1]
    assert t["exit_date"] == bars.index[2]
    assert t["exit_reason"] == "state_flat"


def test_state_flip_closes_old_and_reopens_at_same_open():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),         # decide +1
        (entry, entry + 0.0010, entry - 0.0010, entry + 0.0005),  # enter long @ open
        (entry + 0.002, entry + 0.003, entry + 0.001, entry + 0.0025),  # decide -1 here (flip fires next bar)
        (entry - 0.003, entry - 0.001, entry - 0.005, entry - 0.002),  # flip: close long + open short, same open
    ])
    state = _sig(bars, [1, 1, -1, -1])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 2  # forced close at window end closes the second (short) trade too
    closed_long, opened_short = result["trades"][0], result["trades"][1]
    assert closed_long["direction"] == 1
    assert closed_long["exit_reason"] == "state_flip"
    assert closed_long["exit_date"] == bars.index[3]
    assert opened_short["direction"] == -1
    assert opened_short["entry_date"] == bars.index[3]
    # Both trades share the exact same fill price -- the flip's single open.
    assert opened_short["entry_price"] == pytest.approx(closed_long["exit_price"])
    assert opened_short["entry_price"] == pytest.approx(entry - 0.003)


def test_state_one_cost_per_closed_trade():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0010, entry - 0.0010, entry + 0.0005),
        (entry + 0.002, entry + 0.003, entry + 0.001, entry + 0.0025),
        (entry - 0.003, entry - 0.001, entry - 0.005, entry - 0.002),
    ])
    state = _sig(bars, [1, 1, -1, -1])
    cost_rt = 0.0002
    result = fx.simulate_fx_state(bars, state, cost_rt=cost_rt, overnight=None)
    assert result["trade_count"] == 2
    closed_long = result["trades"][0]
    gross = closed_long["exit_price"] / closed_long["entry_price"] - 1.0
    assert closed_long["return_pct"] == pytest.approx(gross - cost_rt)


def test_state_overnight_financing_charged_per_night_held():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),  # entry bar (day 1)
        (entry, entry + 0.0005, entry - 0.0005, entry),  # day 2
        (entry, entry + 0.0005, entry - 0.0005, entry * 1.001),  # day 3 -- forced close, still holding
    ], start="2024-01-08 20:00", freq="24h")
    state = _sig(bars, [1, 1, 1, 1])
    overnight = {1: 0.0001, -1: 0.00005}
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=overnight)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    nights = (t["exit_date"].normalize() - t["entry_date"].normalize()).days
    assert nights >= 1
    gross = t["exit_price"] / t["entry_price"] - 1.0
    expected_net = gross - nights * overnight[1]
    assert t["return_pct"] == pytest.approx(expected_net)


def test_state_forced_close_at_window_end():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry * 1.002),  # never flips -> forced close
    ])
    state = _sig(bars, [1, 1, 1])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    assert t["exit_reason"] == "end_of_window"
    assert t["exit_price"] == pytest.approx(entry * 1.002)
    assert t["exit_date"] == bars.index[-1]


def test_state_no_tp_sl_position_held_through_large_favorable_and_adverse_moves():
    """No TP/SL bracket at all -- large intra-window swings never trigger an
    exit; only a state flip or window end can close the position."""
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry * 1.20, entry * 0.80, entry),  # huge swing both ways, no exit
        (entry, entry + 0.0005, entry - 0.0005, entry * 1.01),
    ])
    state = _sig(bars, [1, 1, 1, 1])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "end_of_window"


def test_state_result_dict_has_simulate_fx_compatible_shape():
    entry = 1.1000
    bars = _bars([
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry),
        (entry, entry + 0.0005, entry - 0.0005, entry * 1.001),
    ])
    state = _sig(bars, [1, 1, 1])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    for key in ("equity_curve", "trades", "total_return", "max_drawdown", "trade_count"):
        assert key in result
    assert isinstance(result["equity_curve"], pd.Series)
    for key in ("entry_date", "exit_date", "pnl", "return_pct", "exit_reason", "direction"):
        assert key in result["trades"][0]


def test_state_no_signal_ever_produces_zero_trades():
    bars = _bars([(1.1, 1.1005, 1.0995, 1.1)] * 4)
    state = _sig(bars, [0, 0, 0, 0])
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 0
    assert result["total_return"] == pytest.approx(0.0)
