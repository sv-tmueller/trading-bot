from __future__ import annotations

import json
import sys
import types

import pandas as pd
import pytest

from backtest import etf_data
from backtest.etf_data import HoldoutLockedError, load_daily_bars, record_result


_REAL_FETCH_YFINANCE = etf_data._fetch_yfinance


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(ticker):
        raise AssertionError("default yfinance fetch must not run in tests")

    monkeypatch.setattr(etf_data, "_fetch_yfinance", _boom)


def _frame(index) -> pd.DataFrame:
    n = len(index)
    base = pd.Series(range(100, 100 + n), dtype=float).values
    return pd.DataFrame(
        {"Open": base, "High": base + 1, "Low": base - 1, "Close": base + 0.5},
        index=index,
    )


def fake(ticker: str) -> pd.DataFrame:
    return _frame(pd.bdate_range("2019-01-01", "2023-12-29"))


def _dev(tmp_path, cid="c1"):
    return record_result(cid, "development", {"sharpe": 1.0}, pipeline_dir=tmp_path)


def test_development_never_returns_post_2021_rows(tmp_path):
    bars = load_daily_bars(["SPY"], phase="development", fetch=fake, pipeline_dir=tmp_path)
    assert bars["SPY"].index.max() <= pd.Timestamp("2021-12-31")
    assert bars["SPY"].index.min() == pd.Timestamp("2019-01-01")


@pytest.mark.parametrize(
    "index",
    [
        pd.bdate_range("2021-12-20", "2022-01-14", tz="America/New_York"),
        pd.date_range("2021-12-20 05:00", "2022-01-14 05:00", freq="D", tz="UTC"),
    ],
    ids=["new_york", "utc_0500"],
)
def test_development_truncation_handles_tz_aware_index(tmp_path, index):
    bars = load_daily_bars(
        ["SPY"], phase="development", fetch=lambda t: _frame(index), pipeline_dir=tmp_path
    )["SPY"]
    assert bars.index.tz is None
    assert bars.index.max() == pd.Timestamp("2021-12-31")
    assert pd.Timestamp("2021-12-31") in bars.index
    assert not (bars.index.year == 2022).any()


def test_development_strips_utc_midnight_tz_without_converting(tmp_path):
    index = pd.date_range("2021-12-28", "2022-01-05", freq="D", tz="UTC")
    bars = load_daily_bars(
        ["SPY"], phase="development", fetch=lambda t: _frame(index), pipeline_dir=tmp_path
    )["SPY"]
    assert list(bars.index) == list(pd.date_range("2021-12-28", "2021-12-31"))
    assert list(bars["Close"]) == [100.5, 101.5, 102.5, 103.5]


def test_yfinance_all_nan_download_raises(monkeypatch):
    nan_frame = _frame(pd.bdate_range("2021-12-20", "2021-12-24")) * float("nan")
    fake_yf = types.SimpleNamespace(download=lambda *a, **k: nan_frame)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    with pytest.raises(RuntimeError, match="no data for SPY"):
        _REAL_FETCH_YFINANCE("SPY")


def test_holdout_locked_without_development_result(tmp_path):
    with pytest.raises(HoldoutLockedError):
        load_daily_bars(
            ["SPY"], phase="holdout", candidate_id="c1", fetch=fake, pipeline_dir=tmp_path
        )


def test_locked_holdout_never_calls_fetch(tmp_path):
    calls = []

    def counting(ticker):
        calls.append(ticker)
        return fake(ticker)

    with pytest.raises(HoldoutLockedError):
        load_daily_bars(
            ["SPY"], phase="holdout", candidate_id="c1", fetch=counting, pipeline_dir=tmp_path
        )
    with pytest.raises(HoldoutLockedError):
        load_daily_bars(["SPY"], phase="holdout", fetch=counting, pipeline_dir=tmp_path)
    assert calls == []


def test_holdout_unlocks_after_development_result_recorded(tmp_path):
    _dev(tmp_path)
    bars = load_daily_bars(
        ["SPY"], phase="holdout", candidate_id="c1", fetch=fake, pipeline_dir=tmp_path
    )["SPY"]
    assert bars.index.min() < pd.Timestamp("2022-01-01")
    assert bars.index.max() >= pd.Timestamp("2022-01-01")
    assert bars.index.tz is None


def test_holdout_unlock_is_per_candidate(tmp_path):
    _dev(tmp_path, "c1")
    with pytest.raises(HoldoutLockedError):
        load_daily_bars(
            ["SPY"], phase="holdout", candidate_id="c2", fetch=fake, pipeline_dir=tmp_path
        )


def test_holdout_runs_once(tmp_path):
    record_result("c1", "development", {"a": 1}, pipeline_dir=tmp_path)
    record_result("c1", "holdout", {"a": 2}, pipeline_dir=tmp_path)
    with pytest.raises(HoldoutLockedError):
        record_result("c1", "holdout", {"a": 3}, pipeline_dir=tmp_path)
    with pytest.raises(HoldoutLockedError):
        load_daily_bars(
            ["SPY"], phase="holdout", candidate_id="c1", fetch=fake, pipeline_dir=tmp_path
        )


def test_unknown_phase_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        load_daily_bars(["SPY"], phase="bogus", fetch=fake, pipeline_dir=tmp_path)


@pytest.mark.parametrize("bad", ["", "..", "a/b", "c1\n"])
def test_invalid_candidate_id_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        record_result(bad, "development", {}, pipeline_dir=tmp_path)
    with pytest.raises(ValueError):
        load_daily_bars(
            ["SPY"], phase="holdout", candidate_id=bad, fetch=fake, pipeline_dir=tmp_path
        )
    assert list(tmp_path.iterdir()) == []


def test_record_result_unknown_phase_rejected(tmp_path):
    with pytest.raises(ValueError):
        record_result("c1", "bogus", {}, pipeline_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_record_holdout_requires_development_result(tmp_path):
    with pytest.raises(HoldoutLockedError):
        record_result("c1", "holdout", {"a": 1}, pipeline_dir=tmp_path)
    assert not (tmp_path / "c1" / "holdout_result.json").exists()


def test_development_result_cannot_be_rewritten_after_holdout(tmp_path):
    _dev(tmp_path)
    record_result("c1", "holdout", {"a": 1}, pipeline_dir=tmp_path)
    with pytest.raises(HoldoutLockedError):
        record_result("c1", "development", {"a": 2}, pipeline_dir=tmp_path)


def test_development_result_may_be_overwritten_before_holdout(tmp_path):
    record_result("c1", "development", {"v": 1}, pipeline_dir=tmp_path)
    path = record_result("c1", "development", {"v": 2}, pipeline_dir=tmp_path)
    assert json.loads(path.read_text()) == {"v": 2}


def test_unserializable_holdout_payload_does_not_use_up_holdout(tmp_path):
    _dev(tmp_path)
    with pytest.raises(TypeError):
        record_result("c1", "holdout", {"x": object()}, pipeline_dir=tmp_path)
    assert not (tmp_path / "c1" / "holdout_result.json").exists()
    record_result("c1", "holdout", {"x": 1}, pipeline_dir=tmp_path)


def test_record_result_json_is_sorted_indent_2_and_round_trips(tmp_path):
    payload = {"b": 2, "a": {"z": 1, "y": [1, 2]}}
    path = record_result("c1", "development", payload, pipeline_dir=tmp_path)
    assert path == tmp_path / "c1" / "development_result.json"
    text = path.read_text()
    assert json.loads(text) == payload
    assert text == json.dumps(payload, sort_keys=True, indent=2) + "\n"


def test_default_fetch_is_looked_up_at_call_time(tmp_path, monkeypatch):
    used = []

    def fake_default(ticker):
        used.append(ticker)
        return fake(ticker)

    monkeypatch.setattr(etf_data, "_fetch_yfinance", fake_default)
    bars = load_daily_bars(["SPY", "QQQ"], phase="development", fetch=None, pipeline_dir=tmp_path)
    assert used == ["SPY", "QQQ"]
    assert set(bars) == {"SPY", "QQQ"}


def test_frame_missing_ohlc_column_raises_naming_ticker(tmp_path):
    def bad(ticker):
        return fake(ticker).drop(columns=["High"])

    with pytest.raises(ValueError, match="SPY"):
        load_daily_bars(["SPY"], phase="development", fetch=bad, pipeline_dir=tmp_path)
