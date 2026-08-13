"""Tests for backtest/run_fetch_spy_intraday.py (#566 step 1, data feasibility gate).

Offline only: the network seam ``_fetch_page`` is monkeypatched in every test that would
otherwise touch the network. No test ever calls the real Alpaca host.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd
import pytest

import backtest.run_fetch_spy_intraday as fetcher
from backtest.intraday_data import DataQualityError


def _clear_alpaca_env(monkeypatch):
    for name in (
        "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# resolve_keys
# ---------------------------------------------------------------------------

def test_resolve_keys_defaults_to_none_when_unset(monkeypatch):
    _clear_alpaca_env(monkeypatch)
    assert fetcher.resolve_keys() == (None, None)


def test_resolve_keys_prefers_key_id_names(monkeypatch):
    _clear_alpaca_env(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "id-secret")
    monkeypatch.setenv("ALPACA_API_KEY", "ts-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "ts-secret")
    assert fetcher.resolve_keys() == ("id-key", "id-secret")


def test_resolve_keys_falls_back_to_ts_names(monkeypatch):
    _clear_alpaca_env(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY", "ts-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "ts-secret")
    assert fetcher.resolve_keys() == ("ts-key", "ts-secret")


# ---------------------------------------------------------------------------
# fetch_bars
# ---------------------------------------------------------------------------

def test_fetch_bars_raises_without_keys(monkeypatch):
    _clear_alpaca_env(monkeypatch)

    def _boom(*_a, **_k):
        raise AssertionError("network seam must not be called when keys are missing")

    monkeypatch.setattr(fetcher, "_fetch_page", _boom)
    with pytest.raises(fetcher.FetchUnavailableError):
        fetcher.fetch_bars("SPY", "60Min", "2016-01-01", "2016-02-01")


def test_fetch_bars_paginates_and_validates(monkeypatch):
    page1 = {
        "bars": [
            {"t": "2016-01-04T14:30:00Z", "o": 200.0, "h": 201.0, "l": 199.5, "c": 200.5},
            {"t": "2016-01-04T15:30:00Z", "o": 200.5, "h": 202.0, "l": 200.0, "c": 201.5},
        ],
        "next_page_token": "tok-2",
    }
    page2 = {
        "bars": [
            {"t": "2016-01-04T16:30:00Z", "o": 201.5, "h": 203.0, "l": 201.0, "c": 202.5},
        ],
        "next_page_token": None,
    }
    calls = []

    def _fake_page(url, key, secret, *, timeout=30):
        calls.append(url)
        return page1 if "page_token" not in url else page2

    monkeypatch.setattr(fetcher, "_fetch_page", _fake_page)
    df = fetcher.fetch_bars(
        "SPY", "60Min", "2016-01-01", "2016-02-01", key="k", secret="s",
    )
    assert len(calls) == 2
    assert list(df.columns) == ["Open", "High", "Low", "Close"]
    assert len(df) == 3
    assert df.index.is_monotonic_increasing
    assert df["Close"].iloc[0] == 200.5
    assert df["Close"].iloc[-1] == 202.5


def test_fetch_bars_maps_60min_to_1hour_for_the_api_request(monkeypatch):
    """#571 defect fix: Alpaca rejects timeframe=60Min with HTTP 400 (valid grammar is
    1-59Min or 1Hour). The request must carry "1Hour" while the output-file convention
    (SPY_60min.csv, via fetch_and_save's timeframe.lower() stem) is untouched.
    """
    captured = {}

    def _fake_page(url, key, secret, *, timeout=30):
        captured["url"] = url
        return {"bars": [], "next_page_token": None}

    monkeypatch.setattr(fetcher, "_fetch_page", _fake_page)
    fetcher.fetch_bars("SPY", "60Min", "2016-01-01", "2016-02-01", key="k", secret="s")
    assert "timeframe=1Hour" in captured["url"]
    assert "timeframe=60Min" not in captured["url"]


def test_fetch_bars_leaves_other_timeframes_unmapped(monkeypatch):
    captured = {}

    def _fake_page(url, key, secret, *, timeout=30):
        captured["url"] = url
        return {"bars": [], "next_page_token": None}

    monkeypatch.setattr(fetcher, "_fetch_page", _fake_page)
    fetcher.fetch_bars("SPY", "30Min", "2016-01-01", "2016-02-01", key="k", secret="s")
    assert "timeframe=30Min" in captured["url"]


def test_fetch_bars_empty_result_returns_empty_frame(monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_page", lambda *a, **k: {"bars": []})
    df = fetcher.fetch_bars("SPY", "60Min", "2016-01-01", "2016-02-01", key="k", secret="s")
    assert df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close"]


def test_fetch_bars_bad_bar_raises_data_quality_error(monkeypatch):
    bad = {
        "bars": [
            # High below Low: a corrupt/mis-mapped bar, same class validate_ohlc rejects.
            {"t": "2016-01-04T14:30:00Z", "o": 200.0, "h": 190.0, "l": 199.5, "c": 200.5},
        ],
        "next_page_token": None,
    }
    monkeypatch.setattr(fetcher, "_fetch_page", lambda *a, **k: bad)
    with pytest.raises(DataQualityError):
        fetcher.fetch_bars("SPY", "60Min", "2016-01-01", "2016-02-01", key="k", secret="s")


# ---------------------------------------------------------------------------
# sha256 + CSV round trip
# ---------------------------------------------------------------------------

def test_compute_sha256_deterministic(tmp_path):
    p1 = tmp_path / "a.csv"
    p2 = tmp_path / "b.csv"
    p1.write_bytes(b"same content")
    p2.write_bytes(b"same content")
    p3 = tmp_path / "c.csv"
    p3.write_bytes(b"different content")
    assert fetcher.compute_sha256(p1) == fetcher.compute_sha256(p2)
    assert fetcher.compute_sha256(p1) != fetcher.compute_sha256(p3)
    assert fetcher.compute_sha256(p1) == hashlib.sha256(b"same content").hexdigest()


def test_write_csv_then_load_local_roundtrip(tmp_path):
    from backtest.intraday_data import load_local

    idx = pd.date_range("2016-01-04 14:30", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame(
        {"Open": [1.0, 2.0, 3.0], "High": [1.5, 2.5, 3.5],
         "Low": [0.5, 1.5, 2.5], "Close": [1.2, 2.2, 3.2]},
        index=idx,
    )
    path = tmp_path / "SPY_60min.csv"
    fetcher.write_csv(df, path)
    reloaded = load_local(path)
    assert list(reloaded.columns) == ["Open", "High", "Low", "Close"]
    assert len(reloaded) == 3
    assert reloaded["Close"].tolist() == pytest.approx(df["Close"].tolist())


# ---------------------------------------------------------------------------
# fetch_and_save
# ---------------------------------------------------------------------------

def test_fetch_and_save_reports_none_source_when_unavailable(monkeypatch, tmp_path):
    _clear_alpaca_env(monkeypatch)
    report = fetcher.fetch_and_save(
        "SPY", "60Min", "2016-01-01", "2016-02-01", out_dir=tmp_path,
    )
    assert report.source == "none"
    assert report.path is None
    assert report.sha256 is None
    assert report.power.verdict == "UNDERPOWERED"
    assert report.error is not None
    assert not (tmp_path / "SPY_60min.csv").exists()


def test_fetch_and_save_writes_file_and_reports_power(monkeypatch, tmp_path):
    idx = pd.date_range("2016-01-04 14:30", periods=100, freq="h", tz="UTC")
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx,
    )
    monkeypatch.setattr(fetcher, "fetch_bars", lambda *a, **k: df)
    report = fetcher.fetch_and_save(
        "SPY", "60Min", "2016-01-01", "2016-02-01",
        out_dir=tmp_path, key="k", secret="s",
    )
    assert report.source == "alpaca"
    out_path = tmp_path / "SPY_60min.csv"
    assert out_path.exists()
    assert report.path == str(out_path)
    assert report.rows == 100
    assert report.sha256 == fetcher.compute_sha256(out_path)
    assert report.error is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_cli_reports_blocked_count_with_no_keys(monkeypatch, tmp_path, capsys):
    _clear_alpaca_env(monkeypatch)
    rc = fetcher.main([
        "--symbol", "SPY", "--timeframes", "60Min,30Min",
        "--out-dir", str(tmp_path),
    ])
    out = capsys.readouterr().out
    assert rc == 2  # both timeframes blocked
    assert "DATA_BLOCKED" in out
    assert "60Min" in out and "30Min" in out


def test_main_cli_defaults_end_to_previous_utc_date(monkeypatch, tmp_path):
    """#575 round-2 fix (reviewer finding 3 on PR #572): the default `end` must be the
    previous **UTC** date, not the previous LOCAL date -- on UTC+2, local wall-clock
    22:00-24:00 is already tomorrow-local but still today-UTC, so a local-date computation
    can undershoot by a day and re-trigger the recent-SIP-embargo 403 this default exists
    to avoid. Pinned with an injected clock (``fetcher._now_utc``) so the test is
    deterministic regardless of the host's timezone or the day it runs -- no network.
    """
    fixed_now = datetime(2026, 8, 13, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(fetcher, "_now_utc", lambda: fixed_now)

    _clear_alpaca_env(monkeypatch)
    captured_end = {}
    real_fetch_and_save = fetcher.fetch_and_save

    def _spy(symbol, timeframe, start, end, **kwargs):
        captured_end[timeframe] = end
        return real_fetch_and_save(symbol, timeframe, start, end, **kwargs)

    monkeypatch.setattr(fetcher, "fetch_and_save", _spy)
    fetcher.main(["--symbol", "SPY", "--timeframes", "60Min", "--out-dir", str(tmp_path)])
    assert captured_end["60Min"] == "2026-08-12"


def test_main_cli_respects_explicit_end_override(monkeypatch, tmp_path):
    _clear_alpaca_env(monkeypatch)
    captured_end = {}
    real_fetch_and_save = fetcher.fetch_and_save

    def _spy(symbol, timeframe, start, end, **kwargs):
        captured_end[timeframe] = end
        return real_fetch_and_save(symbol, timeframe, start, end, **kwargs)

    monkeypatch.setattr(fetcher, "fetch_and_save", _spy)
    fetcher.main([
        "--symbol", "SPY", "--timeframes", "60Min", "--out-dir", str(tmp_path),
        "--end", "2020-05-01",
    ])
    assert captured_end["60Min"] == "2020-05-01"
