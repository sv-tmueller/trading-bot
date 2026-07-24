"""Tests for backtest/bracket.py — the reusable intra-bar bracket engine (#430).

Offline / synthetic OHLC (no network). Locks the FROZEN fill / tie-break / gap
conventions (see docs/research/2026-07-24-turtle-breakout-verdict.md):

  - exit tested strictly AFTER the entry bar (entry bar never exits);
  - open-gap first: open<=stop -> stop@open (no gift); open>=target -> target@target (cap);
  - intra-bar: low<=stop AND high>=target -> STOP-first tie-break; else stop / target / carry;
  - EOW close-out (weekend-flat) at the last bar of an ISO week;
  - assert exit_date > entry_date;
  - trade-ledger dicts match simulate_from_signal so tax/metrics consume them unchanged;
  - simulate_bracket takes per-entry ABSOLUTE stop/target levels from the caller
    (target may be None), never hardcoding entry +/- kN internally.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.bracket as br


# ---------------------------------------------------------------------------
# _resolve_bar — the frozen fill resolver (pure price logic, no costs).
# ---------------------------------------------------------------------------

def test_resolve_stop_only_intra_bar():
    # open inside bracket, low pierces stop, high does not reach target -> stop
    assert br._resolve_bar(100.0, 105.0, 94.0, 95.0, 110.0) == (95.0, "stop")


def test_resolve_target_only_intra_bar():
    # open inside bracket, high reaches target, low above stop -> target
    assert br._resolve_bar(100.0, 111.0, 97.0, 95.0, 110.0) == (110.0, "target")


def test_resolve_both_hit_is_stop_first():
    # low<=stop AND high>=target within one bar -> conservative STOP-first
    assert br._resolve_bar(100.0, 112.0, 90.0, 95.0, 110.0) == (95.0, "stop")


def test_resolve_gap_down_fills_at_open_no_gift():
    # open gaps below the stop -> fill at the OPEN (adverse, no gift), reason stop
    assert br._resolve_bar(90.0, 92.0, 88.0, 95.0, 110.0) == (90.0, "stop")


def test_resolve_gap_up_caps_at_target():
    # open gaps above the target -> fill at TARGET (D3 conservative cap), reason target
    assert br._resolve_bar(115.0, 118.0, 113.0, 95.0, 110.0) == (110.0, "target")


def test_resolve_carry_returns_none():
    # open inside, neither level touched -> carry (None)
    assert br._resolve_bar(100.0, 108.0, 97.0, 95.0, 110.0) is None


def test_resolve_target_none_never_targets():
    # target=None -> only the stop can fire; a huge high never exits
    assert br._resolve_bar(100.0, 999.0, 97.0, 95.0, None) is None
    assert br._resolve_bar(100.0, 999.0, 94.0, 95.0, None) == (95.0, "stop")
    # gap up with no target -> carry (no target to cap against)
    assert br._resolve_bar(500.0, 999.0, 400.0, 95.0, None) is None


# ---------------------------------------------------------------------------
# simulate_bracket — helpers to build tiny OHLC frames.
# ---------------------------------------------------------------------------

def _frame(dates, o, h, l, c):
    return pd.DataFrame(
        {"Open": o, "High": h, "Low": l, "Close": c},
        index=pd.DatetimeIndex(dates),
    )


def _levels(df, entries, stop, target):
    """Absolute stop/target Series (constant per open trade) aligned to entry bars."""
    trig = pd.Series(entries, index=df.index)
    sp = pd.Series(np.where(entries, stop, np.nan), index=df.index)
    tp = None if target is None else pd.Series(np.where(entries, target, np.nan), index=df.index)
    return trig, sp, tp


ZERO = dict(slippage_bps=0, commission_bps=0)


def test_entry_bar_is_never_tested_for_exit():
    """A stop breach on the ENTRY bar does not exit; the exit lands on the next bar."""
    dates = pd.bdate_range("2020-01-06", periods=4)  # Mon..Thu (same ISO week)
    #                    b0     b1(entry) b2      b3
    df = _frame(dates,
                o=[100, 100, 100, 100],
                h=[101, 120, 105, 105],   # b1 high 120 huge (ignored: entry bar)
                l=[99,  90,  90,  99],    # b1 low 90 below stop (ignored); b2 low 90 hits stop
                c=[100, 100, 96,  100])
    trig, sp, tp = _levels(df, [False, True, False, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["entry_date"] == dates[1]
    assert t["exit_date"] == dates[2]           # exit on the bar AFTER entry
    assert t["exit_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(95.0)
    assert t["exit_date"] > t["entry_date"]


def test_target_exit_next_bar():
    dates = pd.bdate_range("2020-01-06", periods=4)
    df = _frame(dates,
                o=[100, 100, 100, 100],
                h=[101, 101, 115, 105],   # b2 high reaches target 110
                l=[99,  99,  99,  99],
                c=[100, 100, 108, 100])
    trig, sp, tp = _levels(df, [False, True, False, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "target"
    assert t["exit_price"] == pytest.approx(110.0)


def test_gap_down_open_fill_beats_stop_level():
    dates = pd.bdate_range("2020-01-06", periods=3)
    df = _frame(dates,
                o=[100, 100, 90],         # b2 opens at 90, below the 95 stop
                h=[101, 101, 92],
                l=[99,  99,  88],
                c=[100, 100, 90])
    trig, sp, tp = _levels(df, [False, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    t = res["trades"][0]
    assert t["exit_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(90.0)  # filled at the adverse open, no gift


def test_gap_up_caps_at_target():
    dates = pd.bdate_range("2020-01-06", periods=3)
    df = _frame(dates,
                o=[100, 100, 115],        # b2 opens above the 110 target
                h=[101, 101, 118],
                l=[99,  99,  113],
                c=[100, 100, 116])
    trig, sp, tp = _levels(df, [False, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    t = res["trades"][0]
    assert t["exit_reason"] == "target"
    assert t["exit_price"] == pytest.approx(110.0)  # capped, no favorable-gap credit


def test_both_hit_same_bar_is_stop_first():
    dates = pd.bdate_range("2020-01-06", periods=3)
    df = _frame(dates,
                o=[100, 100, 100],
                h=[101, 101, 115],        # reaches target
                l=[99,  99,  90],         # AND pierces stop -> stop-first
                c=[100, 100, 100])
    trig, sp, tp = _levels(df, [False, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    t = res["trades"][0]
    assert t["exit_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(95.0)


def test_eow_close_out_flattens_at_week_end_close():
    """Open across a week end with neither level hit -> flat at the last-of-week close."""
    # Wed Jan 8, Thu Jan 9, Fri Jan 10 (week end), Mon Jan 13
    dates = pd.DatetimeIndex(["2020-01-08", "2020-01-09", "2020-01-10", "2020-01-13"])
    df = _frame(dates,
                o=[100, 100, 100, 100],
                h=[101, 101, 101, 101],   # never reaches target 110
                l=[99,  99,  99,  99],    # never pierces stop 95
                c=[100, 100, 103, 100])   # Fri close 103
    trig, sp, tp = _levels(df, [True, False, False, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "eow"
    assert t["exit_date"] == pd.Timestamp("2020-01-10")   # the Friday
    assert t["exit_price"] == pytest.approx(103.0)


def test_zero_trade_sparse_stretch_is_flat_and_well_formed():
    """No entry signal -> no trades, equity pinned at starting cash, shape intact."""
    dates = pd.bdate_range("2020-01-06", periods=10)
    df = _frame(dates,
                o=[100] * 10, h=[101] * 10, l=[99] * 10, c=[100] * 10)
    trig, sp, tp = _levels(df, [False] * 10, stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, starting_cash=50_000.0, **ZERO)
    assert res["trade_count"] == 0
    assert res["trades"] == []
    assert (res["equity_curve"] == 50_000.0).all()
    assert res["ending_equity"] == pytest.approx(50_000.0)
    assert res["total_return"] == pytest.approx(0.0)


def test_final_open_position_closes_end_of_window():
    dates = pd.bdate_range("2020-01-06", periods=3)  # Mon..Wed, same week -> no EOW
    df = _frame(dates,
                o=[100, 100, 100],
                h=[101, 101, 101],
                l=[99,  99,  99],
                c=[100, 100, 104])
    trig, sp, tp = _levels(df, [False, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "end_of_window"
    assert t["exit_date"] == dates[-1]


def test_ledger_shape_matches_simulate_from_signal_and_tax_consumes_it():
    """Trade dicts carry exactly the 8 keys tax/metrics expect, and tax runs clean."""
    from backtest.tax import apply_tax_to_ledger

    dates = pd.bdate_range("2020-01-06", periods=4)
    df = _frame(dates,
                o=[100, 100, 100, 100],
                h=[101, 101, 115, 105],   # target hit at b2 -> a winning trade
                l=[99,  99,  99,  99],
                c=[100, 100, 108, 100])
    trig, sp, tp = _levels(df, [False, True, False, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    expected = {"entry_date", "exit_date", "entry_price", "exit_price",
                "qty", "pnl", "return_pct", "exit_reason"}
    assert set(res["trades"][0].keys()) == expected
    assert res["trades"][0]["pnl"] > 0  # bought ~100, sold ~110
    after = apply_tax_to_ledger(res["trades"], res["equity_curve"], jurisdiction="US")
    assert (after <= res["equity_curve"] + 1e-6).all()


def test_costs_haircut_entry_and_exit():
    """Non-zero slip/comm haircut both legs (mirrors simulate_from_signal)."""
    dates = pd.bdate_range("2020-01-06", periods=3)
    df = _frame(dates,
                o=[100, 100, 100],
                h=[101, 101, 115],
                l=[99,  99,  99],
                c=[100, 100, 108])
    trig, sp, tp = _levels(df, [False, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, slippage_bps=5, commission_bps=5)
    t = res["trades"][0]
    assert t["entry_price"] == pytest.approx(100.0 * (1 + 5 / 10_000))
    assert t["exit_price"] == pytest.approx(110.0 * (1 - 5 / 10_000))


def test_entry_on_final_bar_is_skipped():
    """A trigger on the very last bar cannot enter (no bar left to exit on)."""
    dates = pd.bdate_range("2020-01-06", periods=3)
    df = _frame(dates,
                o=[100, 100, 100],
                h=[101, 101, 101],
                l=[99,  99,  99],
                c=[100, 100, 100])
    trig, sp, tp = _levels(df, [False, False, True], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 0
    assert res["ending_equity"] == pytest.approx(res["starting_cash"])


def test_no_pyramiding_second_signal_ignored_while_in_position():
    dates = pd.bdate_range("2020-01-06", periods=4)
    df = _frame(dates,
                o=[100, 100, 100, 100],
                h=[101, 101, 101, 101],
                l=[99,  99,  99,  99],
                c=[100, 100, 100, 104])
    # entry at b1; another trigger at b2 must be ignored (already long)
    trig, sp, tp = _levels(df, [False, True, True, False], stop=95.0, target=110.0)
    res = br.simulate_bracket(df, trig, sp, tp, **ZERO)
    assert res["trade_count"] == 1  # single lot, no pyramiding


# ---------------------------------------------------------------------------
# donchian_breakout_signal — no look-ahead 55-breakout (parametrised window).
# ---------------------------------------------------------------------------

def test_donchian_breakout_uses_only_prior_bars():
    idx = pd.bdate_range("2020-01-06", periods=4)
    high = pd.Series([5.0, 6.0, 7.0, 8.0], index=idx)
    close = pd.Series([5.5, 6.5, 10.0, 7.0], index=idx)
    sig = br.donchian_breakout_signal(high, close, window=2)
    # b0,b1: warm-up (NaN rolling max) -> False
    # b2: prior 2 highs [5,6] max 6; close 10 > 6 -> True
    # b3: prior 2 highs [6,7] max 7; close 7 > 7 is False (strict)
    assert list(sig) == [False, False, True, False]


def test_donchian_strict_inequality_no_equal_breakout():
    idx = pd.bdate_range("2020-01-06", periods=3)
    high = pd.Series([10.0, 10.0, 10.0], index=idx)
    close = pd.Series([9.0, 9.0, 10.0], index=idx)  # equals prior high, not >
    sig = br.donchian_breakout_signal(high, close, window=2)
    assert not sig.iloc[-1]
