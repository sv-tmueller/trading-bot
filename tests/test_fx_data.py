"""Tests for backtest/fx_data.py — FXCM H1 EUR/USD archive loader.

All offline: the network seam ``fx_data._fetch_week`` is monkeypatched with
canned in-repo CSV byte fixtures (test scaffolding, not "fabricated price
data" — that prohibition is about research outputs). No test opens a network
connection. Live fetches only ever happen from ``run_fx_plumbing_check.py
--fetch``.
"""
from __future__ import annotations

import gzip
import os

import pandas as pd
import pytest

import backtest.fx_data as fx_data


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_HEADER = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"


def _make_csv_gzip(rows: list) -> bytes:
    text = _HEADER + "\n" + "\n".join(rows) + "\n"
    return gzip.compress(text.encode("utf-8"))


def _row(dt: str, bo, bh, bl, bc, ao, ah, al, ac) -> str:
    return f"{dt},{bo},{bh},{bl},{bc},{ao},{ah},{al},{ac}"


def _normal_week_rows() -> list:
    """A few real-shaped rows, TRUE raw archive bytes (DateTime already UTC —
    the corrected empirical finding, reviewer round-1 must-fix 1; verified
    against the raw cached 2023 week 5 file: first row reads
    ``01/29/2023 22:00:00.000``, a winter Sunday session open)."""
    return [
        _row("01/29/2023 22:00:00.000", 1.08644, 1.08662, 1.08586, 1.08662,
             1.08701, 1.08701, 1.08606, 1.08672),
        _row("01/29/2023 23:00:00.000", 1.08662, 1.08726, 1.0866, 1.08717,
             1.08672, 1.0873, 1.08664, 1.08719),
    ]


def _h1_frame(start: str = "2024-01-08 00:00", n: int = 8, tz: str = "UTC") -> pd.DataFrame:
    """Hand-built H1 frame (bid/ask/mid OHLC) for resample/validator tests."""
    idx = pd.date_range(start, periods=n, freq="1h", tz=tz)
    idx.name = "datetime_utc"
    bid_close = [1.1000 + 0.0001 * i for i in range(n)]
    ask_close = [c + 0.0002 for c in bid_close]
    data = {
        "BidOpen": bid_close, "BidHigh": [c + 0.0003 for c in bid_close],
        "BidLow": [c - 0.0003 for c in bid_close], "BidClose": bid_close,
        "AskOpen": ask_close, "AskHigh": [c + 0.0003 for c in ask_close],
        "AskLow": [c - 0.0003 for c in ask_close], "AskClose": ask_close,
    }
    df = pd.DataFrame(data, index=idx)
    for field in ("Open", "High", "Low", "Close"):
        df[f"Mid{field}"] = (df[f"Bid{field}"] + df[f"Ask{field}"]) / 2.0
    return df


# ---------------------------------------------------------------------------
# parse_week_csv
# ---------------------------------------------------------------------------

def test_parse_week_csv_produces_utc_index_and_mid_columns():
    raw = _make_csv_gzip(_normal_week_rows())
    df = fx_data.parse_week_csv(raw)
    assert len(df) == 2
    # DateTime column is already UTC (corrected finding) -> no offset applied.
    assert df.index[0] == pd.Timestamp("2023-01-29 22:00:00", tz="UTC")
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    # mid = (bid+ask)/2
    assert df["MidClose"].iloc[0] == pytest.approx((1.08662 + 1.08672) / 2)
    assert df["MidOpen"].iloc[0] == pytest.approx((1.08644 + 1.08701) / 2)


def test_parse_week_csv_winter_and_summer_opens_are_both_utc_verbatim():
    """Corrected empirical timezone finding (reviewer round-1 must-fix 1):
    the archive's ``DateTime`` column is already UTC — a winter week's raw
    session open reads Sunday 22:00 and a summer week's reads Sunday 21:00
    (both are the 17:00 ET session open expressed in UTC; verified against
    the raw cached 2023 week 5 / week 28 bytes). Parsing must NOT apply any
    DST-aware timezone conversion — the two opens are used here VERBATIM as
    printed, each landing on its own UTC hour with no further offset."""
    raw = _make_csv_gzip([
        _row("07/09/2023 21:00:00.000", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    ])
    df = fx_data.parse_week_csv(raw)
    assert df.index[0] == pd.Timestamp("2023-07-09 21:00:00", tz="UTC")


def test_parse_week_csv_true_raw_fixture_lands_on_sunday_not_saturday():
    """The bug this must catch: a wrong DST-aware localization (e.g.
    ``tz_localize("America/New_York")`` applied to an already-UTC column)
    shifts a winter Sunday-22:00-UTC open forward into Monday, and — for
    other rows in the week — can land on a spurious Saturday. Parsing the
    TRUE raw fixture (22:00 UTC, winter) must land on Sunday, day-of-week 6."""
    raw = _make_csv_gzip(_normal_week_rows())
    df = fx_data.parse_week_csv(raw)
    assert df.index[0].day_name() == "Sunday"


def test_parse_week_csv_strict_datetime_format_rejects_ambiguous_date():
    """format= parsing must be strict (never dateutil-inferred): a date with
    an invalid month-in-first-position value must raise, not silently
    reinterpret as day-first."""
    bad_rows = [_row("13/01/2024 00:00:00.000", 1, 1, 1, 1, 1, 1, 1, 1)]
    raw = _make_csv_gzip(bad_rows)
    with pytest.raises(ValueError):
        fx_data.parse_week_csv(raw)


def test_parse_week_csv_rejects_unexpected_columns():
    text = "A,B,C\n1,2,3\n"
    raw = gzip.compress(text.encode("utf-8"))
    with pytest.raises(ValueError):
        fx_data.parse_week_csv(raw)


# ---------------------------------------------------------------------------
# Cache round-trip (offline; no network)
# ---------------------------------------------------------------------------

def test_cache_round_trip_write_then_read(tmp_path):
    raw = _make_csv_gzip(_normal_week_rows())
    root = str(tmp_path)
    path = fx_data.write_cache(2023, 5, raw, root=root)
    assert os.path.exists(path)
    read_back = fx_data.read_cache(2023, 5, root=root)
    assert read_back == raw


def test_read_cache_missing_returns_none(tmp_path):
    assert fx_data.read_cache(1999, 1, root=str(tmp_path)) is None


def test_get_week_bytes_cache_hit_never_calls_fetch(tmp_path, monkeypatch):
    root = str(tmp_path)
    raw = _make_csv_gzip(_normal_week_rows())
    fx_data.write_cache(2023, 5, raw, root=root)

    def _boom(year, week):
        raise AssertionError("must not fetch on a cache hit")

    monkeypatch.setattr(fx_data, "_fetch_week", _boom)
    got = fx_data.get_week_bytes(2023, 5, fetch=False, root=root)
    assert got == raw


def test_get_week_bytes_cache_miss_no_fetch_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        fx_data.get_week_bytes(2023, 5, fetch=False, root=str(tmp_path))


def test_get_week_bytes_cache_miss_with_fetch_writes_cache(tmp_path, monkeypatch):
    root = str(tmp_path)
    raw = _make_csv_gzip(_normal_week_rows())
    calls = []

    def _fake_fetch(year, week):
        calls.append((year, week))
        return raw

    monkeypatch.setattr(fx_data, "_fetch_week", _fake_fetch)
    got = fx_data.get_week_bytes(2023, 5, fetch=True, root=root)
    assert got == raw
    assert calls == [(2023, 5)]
    # now cached: a second call must not re-fetch
    got2 = fx_data.get_week_bytes(2023, 5, fetch=True, root=root)
    assert got2 == raw
    assert calls == [(2023, 5)]


def test_fetch_week_raises_week_not_found_on_empty_200_body(monkeypatch):
    """An isolated FXCM CDN artifact observed live (2024 week 35): HTTP 200
    with a zero-byte body. Treated the same as a 404 -- no data for that
    week -- rather than crashing downstream in gzip/CSV parsing."""
    class _FakeResp:
        status_code = 200
        content = b""

        def raise_for_status(self):
            pass

    import requests as _requests
    monkeypatch.setattr(_requests, "get", lambda url, timeout=30: _FakeResp())
    with pytest.raises(fx_data.WeekNotFoundError):
        fx_data._fetch_week(2024, 35)


def test_fetch_week_raises_week_not_found_on_404(monkeypatch):
    class _FakeResp:
        status_code = 404

    import requests as _requests
    monkeypatch.setattr(_requests, "get", lambda url, timeout=30: _FakeResp())
    with pytest.raises(fx_data.WeekNotFoundError):
        fx_data._fetch_week(2099, 1)


def test_get_week_bytes_propagates_week_not_found(tmp_path, monkeypatch):
    def _fake_fetch(year, week):
        raise fx_data.WeekNotFoundError("no such week")

    monkeypatch.setattr(fx_data, "_fetch_week", _fake_fetch)
    with pytest.raises(fx_data.WeekNotFoundError):
        fx_data.get_week_bytes(2099, 1, fetch=True, root=str(tmp_path))


# ---------------------------------------------------------------------------
# resample_to_4h — fixed absolute UTC grid (00/04/08/12/16/20), lead decision
# ---------------------------------------------------------------------------

def test_resample_to_4h_aggregates_ohlc_on_fixed_grid():
    df = _h1_frame(start="2024-01-08 00:00", n=8)  # two full 4h buckets
    resampled, report = fx_data.resample_to_4h(df)
    assert len(resampled) == 2
    assert list(resampled.index) == [
        pd.Timestamp("2024-01-08 00:00", tz="UTC"),
        pd.Timestamp("2024-01-08 04:00", tz="UTC"),
    ]
    # bucket 0 covers H1 bars 0..3
    assert resampled["MidOpen"].iloc[0] == pytest.approx(df["MidOpen"].iloc[0])
    assert resampled["MidClose"].iloc[0] == pytest.approx(df["MidClose"].iloc[3])
    assert resampled["MidHigh"].iloc[0] == pytest.approx(df["MidHigh"].iloc[0:4].max())
    assert resampled["MidLow"].iloc[0] == pytest.approx(df["MidLow"].iloc[0:4].min())
    # bucket 1 covers H1 bars 4..7
    assert resampled["MidOpen"].iloc[1] == pytest.approx(df["MidOpen"].iloc[4])
    assert resampled["MidClose"].iloc[1] == pytest.approx(df["MidClose"].iloc[7])
    assert report["n_bars"] == 2
    assert report["n_partial_boundary_buckets"] == 0


def test_resample_to_4h_counts_partial_boundary_bucket():
    # Only 2 of the 4 hours in the [00:00, 04:00) bucket are present.
    df = _h1_frame(start="2024-01-08 02:00", n=6)
    resampled, report = fx_data.resample_to_4h(df)
    assert report["n_partial_boundary_buckets"] >= 1
    assert len(resampled) == report["n_bars"]


def test_drop_in_progress_bar_removes_last_row():
    """No-look-ahead convention (SUB_PLAN): the final resampled 4h bar is
    dropped AT LOAD, in fx_data.py — not left to callers to remember."""
    df = _h1_frame(start="2024-01-08 00:00", n=8)
    resampled, _ = fx_data.resample_to_4h(df)
    assert len(resampled) == 2
    dropped = fx_data.drop_in_progress_bar(resampled)
    assert len(dropped) == 1
    assert list(dropped.index) == [pd.Timestamp("2024-01-08 00:00", tz="UTC")]


def test_drop_in_progress_bar_empty_frame_returns_empty():
    df = _h1_frame(start="2024-01-08 00:00", n=8)
    resampled, _ = fx_data.resample_to_4h(df)
    empty = resampled.iloc[0:0]
    dropped = fx_data.drop_in_progress_bar(empty)
    assert len(dropped) == 0


def test_resample_to_4h_drops_empty_weekend_buckets():
    # A gap of a day+ between two bars must not produce all-NaN empty rows.
    idx = pd.DatetimeIndex(
        ["2024-01-08 00:00", "2024-01-10 00:00"], tz="UTC", name="datetime_utc"
    )
    df = pd.DataFrame(
        {c: [1.1, 1.2] for c in
         ["BidOpen", "BidHigh", "BidLow", "BidClose",
          "AskOpen", "AskHigh", "AskLow", "AskClose",
          "MidOpen", "MidHigh", "MidLow", "MidClose"]},
        index=idx,
    )
    resampled, _ = fx_data.resample_to_4h(df)
    assert not resampled["MidClose"].isna().any()


# ---------------------------------------------------------------------------
# Validation checks — each fires on a deliberately broken fixture
# ---------------------------------------------------------------------------

def test_check_duplicates_fires_on_repeated_timestamp():
    df = _h1_frame(n=4)
    broken = pd.concat([df, df.iloc[[0]]]).sort_index()
    report = fx_data.check_duplicates(broken)
    assert report["n_duplicates"] == 1


def test_check_duplicates_clean_on_normal_fixture():
    df = _h1_frame(n=4)
    report = fx_data.check_duplicates(df)
    assert report["n_duplicates"] == 0


def test_check_monotonic_fires_on_out_of_order_index():
    df = _h1_frame(n=4)
    broken = df.iloc[[0, 2, 1, 3]]
    report = fx_data.check_monotonic(broken)
    assert report["is_monotonic"] is False
    assert report["n_non_monotonic"] >= 1


def test_check_monotonic_clean_on_normal_fixture():
    df = _h1_frame(n=4)
    report = fx_data.check_monotonic(df)
    assert report["is_monotonic"] is True
    assert report["n_non_monotonic"] == 0


def test_check_gaps_fires_on_missing_hour():
    df = _h1_frame(n=4)
    broken = df.drop(df.index[2])  # remove the third hourly bar -> a 2h gap
    report = fx_data.check_gaps(broken)
    assert report["n_gaps"] == 1


def test_check_gaps_clean_on_contiguous_hourly_fixture():
    df = _h1_frame(n=4)
    report = fx_data.check_gaps(df)
    assert report["n_gaps"] == 0


def test_check_ohlc_coherence_fires_on_low_above_close():
    df = _h1_frame(n=2).copy()
    df.loc[df.index[0], "BidLow"] = df.loc[df.index[0], "BidClose"] + 1.0
    report = fx_data.check_ohlc_coherence(df)
    assert report["n_coherence_violations"] >= 1


def test_check_ohlc_coherence_fires_on_crossed_quotes():
    df = _h1_frame(n=2).copy()
    df.loc[df.index[0], "AskClose"] = df.loc[df.index[0], "BidClose"] - 0.01
    report = fx_data.check_ohlc_coherence(df)
    assert report["n_crossed_quotes"] >= 1


def test_check_ohlc_coherence_fires_on_non_positive_price():
    df = _h1_frame(n=2).copy()
    df.loc[df.index[0], "BidOpen"] = 0.0
    report = fx_data.check_ohlc_coherence(df)
    assert report["n_non_positive_prices"] >= 1


def test_check_ohlc_coherence_fires_on_broken_mid_field():
    """Mid OHLC is checked too — it's what fx_execution.simulate_fx actually
    consumes, so its coherence must be verified independently of Bid/Ask."""
    df = _h1_frame(n=2).copy()
    df.loc[df.index[0], "MidLow"] = df.loc[df.index[0], "MidClose"] + 1.0
    report = fx_data.check_ohlc_coherence(df)
    assert report["n_coherence_violations"] >= 1


def test_check_ohlc_coherence_clean_on_normal_fixture():
    df = _h1_frame(n=4)
    report = fx_data.check_ohlc_coherence(df)
    assert report["n_coherence_violations"] == 0
    assert report["n_crossed_quotes"] == 0
    assert report["n_non_positive_prices"] == 0


# ---------------------------------------------------------------------------
# check_weekend_bars — the mechanical "zero Saturday bars" check (reviewer
# round-1 must-fix 1: would have caught the timezone bug).
# ---------------------------------------------------------------------------

def test_check_weekend_bars_zero_saturdays_on_correctly_parsed_week():
    """A correctly-parsed week (true UTC, no bogus DST shift) has FX
    market-hours bars on Sunday (session open) but NEVER on Saturday."""
    raw = _make_csv_gzip(_normal_week_rows())
    df = fx_data.parse_week_csv(raw)
    report = fx_data.check_weekend_bars(df)
    assert report["n_saturday_bars"] == 0
    assert report["n_sunday_bars"] == 2  # both fixture rows are Sunday 22:00/23:00 UTC


def test_check_weekend_bars_fires_on_saturday_timestamp():
    """Reproduces the bug class: a bar that lands on Saturday must be
    flagged — this is the check that would have caught the reviewer's
    must-fix 1 (a wrong tz_localize shifted bars onto impossible Saturdays)."""
    idx = pd.DatetimeIndex(
        ["2023-01-28 03:00", "2023-01-29 22:00"], tz="UTC", name="datetime_utc"
    )  # 2023-01-28 is a Saturday
    df = pd.DataFrame(
        {c: [1.1, 1.2] for c in
         ["BidOpen", "BidHigh", "BidLow", "BidClose",
          "AskOpen", "AskHigh", "AskLow", "AskClose",
          "MidOpen", "MidHigh", "MidLow", "MidClose"]},
        index=idx,
    )
    report = fx_data.check_weekend_bars(df)
    assert report["n_saturday_bars"] == 1
    assert report["n_sunday_bars"] == 1


# ---------------------------------------------------------------------------
# Empirical spread series arithmetic
# ---------------------------------------------------------------------------

def test_empirical_spread_pips_arithmetic():
    df = _h1_frame(n=2)
    spread = fx_data.empirical_spread_pips(df)
    expected = (df["AskClose"] - df["BidClose"]) / 0.0001
    pd.testing.assert_series_equal(spread, expected, check_names=False)
    # By construction in _h1_frame, AskClose = BidClose + 0.0002 -> 2.0 pips
    assert spread.iloc[0] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Weekly completeness report (file + row-count) — pure, no network
# ---------------------------------------------------------------------------

def test_completeness_report_flags_missing_weeks_and_rows():
    week_rows = {
        2023: {w: 120 for w in range(1, 53)} | {53: None},  # week 53 missing
    }
    report = fx_data.completeness_report(week_rows)
    assert report[2023]["n_missing_weeks"] == 1
    assert report[2023]["missing_weeks"] == [53]
    assert report[2023]["pct_missing_weeks"] == pytest.approx(1 / 53)
    assert report[2023]["n_rows_found"] == 120 * 52


def test_completeness_report_all_present_zero_pct_missing():
    week_rows = {2023: {w: 120 for w in range(1, 53)}}
    report = fx_data.completeness_report(week_rows)
    assert report[2023]["n_missing_weeks"] == 0
    assert report[2023]["pct_missing_weeks"] == 0.0
    assert report[2023]["pct_rows_missing"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# drop_saturday_bars (#376 -- the frozen carve-out, SUB_PLAN §4)
# ---------------------------------------------------------------------------

def test_drop_saturday_bars_drops_exactly_saturday_rows_and_returns_count():
    idx = pd.DatetimeIndex(
        [
            "2023-01-27 20:00",  # Friday
            "2023-01-28 03:00",  # Saturday
            "2023-01-28 15:00",  # Saturday
            "2023-01-29 22:00",  # Sunday
        ],
        tz="UTC", name="datetime_utc",
    )
    df = pd.DataFrame({"MidClose": [1.1, 1.2, 1.3, 1.4]}, index=idx)
    result, n_dropped = fx_data.drop_saturday_bars(df)
    assert n_dropped == 2
    assert len(result) == 2
    assert list(result.index) == [idx[0], idx[3]]


def test_drop_saturday_bars_no_saturdays_is_a_no_op():
    idx = pd.DatetimeIndex(
        ["2023-01-27 20:00", "2023-01-29 22:00"], tz="UTC", name="datetime_utc",
    )
    df = pd.DataFrame({"MidClose": [1.1, 1.4]}, index=idx)
    result, n_dropped = fx_data.drop_saturday_bars(df)
    assert n_dropped == 0
    assert len(result) == 2


def test_drop_saturday_bars_check_weekend_bars_zero_afterward():
    idx = pd.DatetimeIndex(
        [
            "2023-01-27 20:00",  # Friday
            "2023-01-28 03:00",  # Saturday
            "2023-01-29 22:00",  # Sunday
        ],
        tz="UTC", name="datetime_utc",
    )
    df = pd.DataFrame({"MidClose": [1.1, 1.2, 1.4]}, index=idx)
    result, _ = fx_data.drop_saturday_bars(df)
    report = fx_data.check_weekend_bars(result)
    assert report["n_saturday_bars"] == 0
    assert report["n_sunday_bars"] == 1
