"""Tests for backtest/run_orb_probe.py wiring (#431).

Offline / synthetic intraday OHLC (no network): ``_fetch`` is monkeypatched. Locks the
frozen ORB rule — opening range = first bar of the session, long-only entry at the first
Close break above the OR high (entered next open, one per session, never on the OR bar or
across a session), OR-low stop, session/EOD close-out — plus the depth probe, the
random/always-in baselines, and the #430 should-fix data-unavailable guard.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_orb_probe as orb


def _session_bars(day: pd.Timestamp, bars: int, o, h, l, c) -> pd.DataFrame:
    times = [day + pd.Timedelta(hours=13, minutes=30) + pd.Timedelta(minutes=5 * i)
             for i in range(bars)]
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c},
                        index=pd.DatetimeIndex(times))


def _synth_intraday(n_sessions: int, bars: int = 12, seed: int = 0,
                    start: str = "2024-01-02") -> pd.DataFrame:
    """Up-drifting 5-min sessions so a Close break above the OR high occurs each session."""
    rng = np.random.default_rng(seed)
    day0 = pd.Timestamp(start, tz="UTC")
    frames, made, d = [], 0, 0
    while made < n_sessions:
        ts0 = day0 + pd.Timedelta(days=d)
        if ts0.weekday() < 5:
            drift = rng.uniform(0.02, 0.06)
            closes = 100.0 + drift * np.arange(bars) + rng.normal(0, 0.005, bars)
            opens = np.concatenate([[100.0], closes[:-1]])
            highs = np.maximum(opens, closes) + 0.15
            lows = np.minimum(opens, closes) - 0.15
            frames.append(_session_bars(ts0, bars, opens, highs, lows, closes))
            made += 1
        d += 1
    return pd.concat(frames)


# ---------------------------------------------------------------------------
# Opening range + entry trigger (the frozen signal).
# ---------------------------------------------------------------------------

def test_opening_range_is_first_bar_broadcast():
    df = _synth_intraday(2, bars=6, seed=1)
    or_high, or_low, is_first, sess = orb._opening_range(df)
    for _key, grp in df.groupby(sess):
        assert (or_high.loc[grp.index] == grp["High"].iloc[0]).all()
        assert (or_low.loc[grp.index] == grp["Low"].iloc[0]).all()
    # exactly one first-bar flag per session
    assert int(is_first.sum()) == 2


def test_entry_is_first_close_break_next_open_one_per_session():
    """One long entry per session, at the bar AFTER the first Close break above OR high."""
    # Single session: OR bar high=100.5; close breaks above at bar 2 -> entry at bar 3.
    day = pd.Timestamp("2024-01-02", tz="UTC")
    df = _session_bars(day, 5,
                       o=[100, 100, 100, 101, 101],
                       h=[100.5, 100.4, 101.0, 101.5, 101.5],  # OR high 100.5
                       l=[99.5, 99.8, 100.0, 100.5, 100.5],
                       c=[100, 100.2, 101.0, 101.2, 101.2])     # bar2 close 101.0 > 100.5
    trig = orb._entry_trigger(df)
    assert list(trig) == [False, False, False, True, False]     # enter bar3 (next open)


def test_entry_never_on_or_bar_or_across_session():
    df = _synth_intraday(4, bars=10, seed=3)
    _oh, _ol, is_first, sess = orb._opening_range(df)
    trig = orb._entry_trigger(df)
    # no trigger on any session's opening (OR) bar
    assert not (trig & is_first).any()
    # at most one entry per session (one-per-session rule)
    assert (trig.groupby(sess).sum() <= 1).all()


# ---------------------------------------------------------------------------
# Cell construction — long-only, session-flat, correct geometry.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("r", [None, 5.0, 10.0])
def test_build_cell_trades_are_long_and_flat_by_session(r):
    df = _synth_intraday(6, bars=12, seed=5)
    sim = orb._build_cell(df, r)
    assert sim["trade_count"] >= 1
    for t in sim["trades"]:
        assert t["exit_date"] > t["entry_date"]
        assert t["exit_reason"] in {"stop", "target", "session", "end_of_window"}
        # never held overnight: entry and exit share a session (same calendar date)
        assert t["entry_date"].normalize() == t["exit_date"].normalize()


def test_stop_only_variant_never_targets():
    df = _synth_intraday(6, bars=12, seed=7)
    sim = orb._build_cell(df, None)             # exit-at-close variant, no target
    assert all(t["exit_reason"] != "target" for t in sim["trades"])
    assert sim["trade_count"] >= 1


def test_random_cell_is_seed_reproducible():
    df = _synth_intraday(6, bars=12, seed=9)
    a = orb._build_random_cell(df, 5.0, seed=99)
    b = orb._build_random_cell(df, 5.0, seed=99)
    assert a["trade_count"] == b["trade_count"]
    assert a["ending_equity"] == pytest.approx(b["ending_equity"])


# ---------------------------------------------------------------------------
# Probe driver + the #430 should-fix data-unavailable guard.
# ---------------------------------------------------------------------------

def test_run_orb_reports_depth_and_three_cells(monkeypatch):
    df = _synth_intraday(8, bars=12, seed=11)
    monkeypatch.setattr(orb, "_fetch", lambda s, e: ("synthetic", df))
    res = orb.run_orb(end=pd.Timestamp("2024-03-01").date())
    assert res["data_available"] is True
    assert res["depth"]["source"] == "synthetic"
    assert res["depth"]["n_sessions"] == 8
    assert set(res["cells"].keys()) == set(orb.TARGET_VARIANTS)
    for r in orb.TARGET_VARIANTS:
        cell = res["cells"][r]
        assert "random" in cell and "always_in" in cell and "metrics" in cell


def test_run_orb_underpowered_flag_on_shallow_sample(monkeypatch):
    df = _synth_intraday(8, bars=12, seed=13)
    monkeypatch.setattr(orb, "_fetch", lambda s, e: ("synthetic", df))
    res = orb.run_orb(end=pd.Timestamp("2024-03-01").date())
    assert res["powered"] is False               # 8 sessions << PROBE_MIN_SESSIONS


def test_run_orb_empty_fetch_reports_unavailable_not_indexerror(monkeypatch):
    """#430 should-fix: an empty fetch degrades to data_available=False, never IndexError."""
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    monkeypatch.setattr(orb, "_fetch", lambda s, e: ("yfinance", empty))
    res = orb.run_orb(end=pd.Timestamp("2024-03-01").date())
    assert res["data_available"] is False
    assert res["cells"] == {}
    assert res["depth"]["n_bars"] == 0


def test_fetch_falls_back_to_yfinance_when_alpaca_none(monkeypatch):
    monkeypatch.setattr(orb, "_fetch_alpaca", lambda s, e: None)
    sentinel = _synth_intraday(2, bars=6, seed=15)
    monkeypatch.setattr(orb, "_fetch_yfinance", lambda s, e: sentinel)
    src, df = orb._fetch(orb.PROBE_START, pd.Timestamp("2024-03-01").date())
    assert src == "yfinance"
    assert len(df) == len(sentinel)
