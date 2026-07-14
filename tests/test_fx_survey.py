"""Tests for backtest/fx_survey.py -- composition library for the pre-
registered FX signal survey (#376). All offline: no network, no cache
access -- ``fx_data.get_week_bytes``/``read_cache`` are never touched by any
test in this file except via explicit monkeypatch of the network seam.
"""
from __future__ import annotations

import gzip

import numpy as np
import pandas as pd
import pytest

from backtest import fx_survey


# ---------------------------------------------------------------------------
# prepare_history -- load -> validate/BLOCKED gate -> Saturday carve-out ->
# resample -> drop in-progress bar (SUB_PLAN §4)
# ---------------------------------------------------------------------------

_HEADER = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"


def _make_csv_gzip(rows: list) -> bytes:
    text = _HEADER + "\n" + "\n".join(rows) + "\n"
    return gzip.compress(text.encode("utf-8"))


def _row(dt: str, bo, bh, bl, bc, ao, ah, al, ac) -> str:
    return f"{dt},{bo},{bh},{bl},{bc},{ao},{ah},{al},{ac}"


def _week_of_hourly_rows(start: str, n: int = 24) -> list:
    """n contiguous hourly rows starting at `start` (MM/DD/YYYY HH:MM:SS.000)."""
    idx = pd.date_range(start, periods=n, freq="1h")
    rows = []
    for ts in idx:
        dt = ts.strftime("%m/%d/%Y %H:%M:%S.000")
        rows.append(_row(dt, 1.10, 1.11, 1.09, 1.105, 1.101, 1.111, 1.091, 1.106))
    return rows


def test_prepare_history_offline_pipeline_order(monkeypatch):
    """Cache-hit path only (no network): one cached week of clean data, one
    Saturday-stamped row injected to prove the carve-out actually runs."""
    from backtest import fx_data

    # Week starting Sunday 2023-01-29 22:00 UTC (a normal FX week open) plus
    # one deliberately Saturday-stamped extra row (2023-02-04 is a Saturday).
    rows = _week_of_hourly_rows("2023-01-29 22:00", n=20)
    rows.append(_row("02/04/2023 12:00:00.000", 1.10, 1.11, 1.09, 1.105, 1.101, 1.111, 1.091, 1.106))
    raw = _make_csv_gzip(rows)

    def fake_read_cache(year, week, *, root=fx_data.CACHE_ROOT):
        if year == 2023 and week == 5:
            return raw
        return None

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        cached = fake_read_cache(year, week, root=root)
        if cached is not None:
            return cached
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "read_cache", fake_read_cache)
    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)

    result = fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)

    assert result["n_saturday_dropped"] == 1
    bars_4h = result["bars_4h"]
    assert len(bars_4h) > 0
    # No Saturday-UTC bars survive resampling.
    assert (bars_4h.index.dayofweek == 5).sum() == 0
    # The in-progress final bar was dropped (bars_4h shorter than the raw resample).
    assert result["resample_report"]["n_bars"] > len(bars_4h)


def test_prepare_history_blocked_on_no_cached_data(monkeypatch):
    from backtest import fx_data

    monkeypatch.setattr(fx_data, "read_cache", lambda year, week, **kw: None)

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)

    with pytest.raises(SystemExit, match="BLOCKED"):
        fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)


# ---------------------------------------------------------------------------
# slice_calendar_year_windows (spec §5)
# ---------------------------------------------------------------------------

def _make_4h_index(start: str, end: str) -> pd.DatetimeIndex:
    idx = pd.date_range(start, end, freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    return idx


def test_slice_calendar_year_windows_jan1_utc_boundaries():
    idx = _make_4h_index("2012-06-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    w2013 = next(w for w in windows if w["year"] == 2013)
    assert w2013["test_start"] == pd.Timestamp("2013-01-01", tz="UTC")
    assert w2013["test_end"] == pd.Timestamp("2014-01-01", tz="UTC")


def test_slice_calendar_year_windows_exactly_300_bar_positional_pre_roll():
    idx = _make_4h_index("2012-01-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    w2013 = next(w for w in windows if w["year"] == 2013)
    ts_pos = idx.searchsorted(w2013["test_start"], side="left")
    expected_pre_roll_start = idx[max(0, ts_pos - 300)]
    assert w2013["pre_roll_start"] == expected_pre_roll_start


def test_slice_calendar_year_windows_2012_never_appears_as_a_window():
    idx = _make_4h_index("2012-01-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    years = [w["year"] for w in windows]
    assert 2012 not in years
    assert 2013 in years


def test_slice_calendar_year_windows_2026_excluded_from_scoring():
    idx = _make_4h_index("2012-01-01", "2026-05-01")
    windows = fx_survey.slice_calendar_year_windows(
        idx, first_test_year=2013, pre_roll_bars=300, excluded_years=(2026,)
    )
    scored_years = [w["year"] for w in windows if w["scored"]]
    unscored_years = [w["year"] for w in windows if not w["scored"]]
    assert 2026 in unscored_years
    assert 2026 not in scored_years
    assert scored_years == list(range(2013, 2026))
    assert len(scored_years) == 13


def test_slice_calendar_year_windows_stops_when_data_runs_out():
    idx = _make_4h_index("2012-01-01", "2015-01-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    years = [w["year"] for w in windows]
    assert max(years) <= 2015
    assert all(y >= 2013 for y in years)
