"""Tests for backtest/intraday_data.py — local bar loading + power accounting (#434).

Offline (tmp files only, no network). Locks:
  - flexible column/timestamp naming, normalised to OHLC on a UTC DatetimeIndex;
  - corrupt or mis-mapped frames fail LOUDLY rather than simulating nonsense;
  - the power verdict is the single gate deciding read vs plumbing-smoke;
  - a missing file resolves to DATA-BLOCKED with df=None, never to fabricated bars.
"""
from __future__ import annotations

import pandas as pd
import pytest

import backtest.intraday_data as idata


def _good_frame(n=120, start="2020-01-06 14:30", freq="5min"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx
    )


def _write_csv(tmp_path, df, name="bars.csv", index_label="timestamp"):
    p = tmp_path / name
    df.to_csv(p, index_label=index_label)
    return p


# ---------------------------------------------------------------------------
# Column / timestamp normalisation
# ---------------------------------------------------------------------------

def test_load_local_reads_canonical_csv(tmp_path):
    p = _write_csv(tmp_path, _good_frame())
    out = idata.load_local(p)
    assert list(out.columns) == list(idata.OHLC)
    assert isinstance(out.index, pd.DatetimeIndex)
    assert len(out) == 120


def test_load_local_accepts_lowercase_and_short_aliases(tmp_path):
    df = _good_frame(90).rename(
        columns={"Open": "o", "High": "h", "Low": "l", "Close": "c"}
    )
    out = idata.load_local(_write_csv(tmp_path, df, index_label="time"))
    assert list(out.columns) == list(idata.OHLC)
    assert out["Open"].iloc[0] == pytest.approx(100.0)


def test_load_local_accepts_a_datetime_column_named_date(tmp_path):
    df = _good_frame(90)
    out = idata.load_local(_write_csv(tmp_path, df, index_label="date"))
    assert len(out) == 90


def test_load_local_sorts_and_dedupes(tmp_path):
    df = _good_frame(90)
    shuffled = pd.concat([df.iloc[50:], df.iloc[:50], df.iloc[:5]])  # unsorted + dupes
    out = idata.load_local(_write_csv(tmp_path, shuffled))
    assert out.index.is_monotonic_increasing
    assert not out.index.duplicated().any()
    assert len(out) == 90


def test_missing_column_raises(tmp_path):
    df = _good_frame(90).drop(columns=["Low"])
    with pytest.raises(idata.DataQualityError, match="missing OHLC column"):
        idata.load_local(_write_csv(tmp_path, df))


def test_unparseable_timestamp_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,Open,High,Low,Close\nnot-a-date,1,2,0.5,1.5\n")
    with pytest.raises(idata.DataQualityError, match="unparseable"):
        idata.load_local(p)


def test_no_timestamp_anywhere_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Open,High,Low,Close\n1,2,0.5,1.5\n")
    with pytest.raises(idata.DataQualityError, match="no recognisable timestamp"):
        idata.load_local(p)


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "bars.xlsx"
    p.write_text("x")
    with pytest.raises(idata.DataQualityError, match="unsupported file type"):
        idata.load_local(p)


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        idata.load_local(tmp_path / "nope.csv")


# ---------------------------------------------------------------------------
# validate_ohlc — corrupt frames must fail loudly
# ---------------------------------------------------------------------------

def test_high_below_low_is_rejected():
    df = _good_frame(90)
    df.iloc[10, df.columns.get_loc("High")] = 1.0     # High far below Low
    with pytest.raises(idata.DataQualityError, match="do not bracket"):
        idata.validate_ohlc(df)


def test_high_not_bracketing_close_is_rejected():
    """The classic mis-mapped-column signature: a Close above the bar's High."""
    df = _good_frame(90)
    df.iloc[5, df.columns.get_loc("Close")] = 500.0
    with pytest.raises(idata.DataQualityError, match="do not bracket"):
        idata.validate_ohlc(df)


def test_non_positive_price_is_rejected():
    df = _good_frame(90)
    df.iloc[3, df.columns.get_loc("Low")] = 0.0
    with pytest.raises(idata.DataQualityError, match="non-positive"):
        idata.validate_ohlc(df)


def test_nan_is_rejected():
    df = _good_frame(90)
    df.iloc[7, df.columns.get_loc("Open")] = float("nan")
    with pytest.raises(idata.DataQualityError, match="NaN"):
        idata.validate_ohlc(df)


def test_valid_frame_passes_through_unchanged():
    df = _good_frame(90)
    out = idata.validate_ohlc(df)
    assert len(out) == 90
    assert out["High"].iloc[0] == pytest.approx(101.0)


# ---------------------------------------------------------------------------
# describe_power — the honesty gate
# ---------------------------------------------------------------------------

def test_empty_frame_is_underpowered():
    rep = idata.describe_power(_good_frame(0))
    assert rep.verdict == "UNDERPOWERED"
    assert not rep.is_readable
    assert "empty" in rep.reason


def test_tiny_frame_is_underpowered_on_bar_count():
    rep = idata.describe_power(_good_frame(10))
    assert rep.verdict == "UNDERPOWERED"
    assert "bar minimum" in rep.reason


def test_shallow_sample_is_underpowered_on_sessions():
    """The #431 situation: enough bars, nowhere near enough sessions."""
    idx = pd.date_range("2026-04-29 14:30", periods=4610, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx
    )
    rep = idata.describe_power(df)
    assert rep.verdict == "UNDERPOWERED"
    assert not rep.is_readable
    assert "plumbing smoke" in rep.reason


def test_deep_but_short_span_is_directional_only():
    """Enough sessions, but fewer than 13 complete 12-month windows."""
    idx = pd.to_datetime(
        [f"{d:%Y-%m-%d} 14:30" for d in pd.bdate_range("2020-01-06", periods=600)],
        utc=True,
    )
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx
    )
    rep = idata.describe_power(df)
    assert rep.verdict == "DIRECTIONAL"
    assert rep.is_readable                      # readable, but NOT gate-eligible
    assert "promotion bar" in rep.reason


def test_deep_and_long_span_is_promotable():
    idx = pd.to_datetime(
        [f"{d:%Y-%m-%d} 14:30" for d in pd.bdate_range("2010-01-04", periods=4000)],
        utc=True,
    )
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx
    )
    rep = idata.describe_power(df)
    assert rep.verdict == "PROMOTABLE"
    assert rep.is_readable
    assert rep.n_windows >= idata.PROMOTION_N_W


def test_power_summary_is_human_readable():
    rep = idata.describe_power(_good_frame(120))
    s = rep.summary()
    assert rep.verdict in s and "sessions" in s and "n_w=" in s


# ---------------------------------------------------------------------------
# regular_session
# ---------------------------------------------------------------------------

def test_regular_session_drops_out_of_hours_bars():
    idx = pd.to_datetime(
        ["2020-01-06 09:00", "2020-01-06 14:30", "2020-01-06 20:00",
         "2020-01-06 23:30"], utc=True)
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx
    )
    out = idata.regular_session(df)
    assert len(out) == 2
    assert out.index[0].hour == 14


def test_regular_session_on_empty_frame_is_a_noop():
    empty = _good_frame(0)
    assert idata.regular_session(empty).empty


# ---------------------------------------------------------------------------
# resolve_intraday — must never invent data
# ---------------------------------------------------------------------------

def test_resolve_finds_an_explicit_local_file(tmp_path):
    p = _write_csv(tmp_path, _good_frame(120))
    source, df, rep = idata.resolve_intraday(local_path=p)
    assert source.startswith("local:")
    assert df is not None and len(df) == 120
    assert rep.n_bars == 120


def test_resolve_with_nothing_available_is_data_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                 # no data/ dirs exist here
    source, df, rep = idata.resolve_intraday()
    assert source == "none"
    assert df is None                            # never a fabricated frame
    assert rep.verdict == "UNDERPOWERED"
    assert not rep.is_readable
    assert "egress-denied" in rep.reason


def test_resolve_finds_a_conventional_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "data" / "intraday"
    d.mkdir(parents=True)
    _good_frame(120).to_csv(d / "SPY_5min.csv", index_label="timestamp")
    source, df, rep = idata.resolve_intraday(symbol="SPY", timeframe="5Min")
    assert "SPY_5min.csv" in source
    assert df is not None and len(df) == 120
