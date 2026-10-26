"""Offline tests for the yfinance vs Alpaca daily parity check."""
from __future__ import annotations

import inspect
import math

import numpy as np
import pandas as pd
import pytest

import backtest.etf_data as etf_data
import backtest.run_etf_parity as parity
import backtest.run_fetch_spy_intraday as fetch_mod
from backtest.run_etf_parity import (
    ALPACA_END,
    MEDIAN_ABS_DIFF_BPS_MAX,
    P99_ABS_DIFF_BPS_MAX,
    compare_daily_returns,
    format_row,
    main,
    run_parity,
)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("unmocked network/Alpaca call")

    monkeypatch.setattr(etf_data, "_fetch_yfinance", _boom)
    monkeypatch.setattr(parity, "fetch_bars", _boom)
    monkeypatch.setattr(fetch_mod, "_fetch_page", _boom)
    for name in (
        "ALPACA_API_KEY_ID",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


N_RETURNS = 500


def _base_returns() -> np.ndarray:
    return np.random.default_rng(0).normal(0.0, 0.01, N_RETURNS)


def _closes(returns: np.ndarray, index: pd.DatetimeIndex) -> pd.Series:
    values = 100.0 * np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    return pd.Series(values, index=index)


def _index() -> pd.DatetimeIndex:
    return pd.bdate_range("2019-01-02", periods=N_RETURNS + 1)


def _pair(perturb=None):
    """yf closes from base returns; alpaca closes from perturbed returns.

    Building from returns means each perturbation hits exactly one return
    (a level spike in the closes would hit two).
    """
    base = _base_returns()
    alt = base.copy()
    if perturb is not None:
        perturb(alt)
    idx = _index()
    return _closes(base, idx), _closes(alt, idx)


def _frame(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close})


# -- acceptance fixtures ----------------------------------------------------


def test_identical_series_pass_with_zero_diffs():
    yf, al = _pair()
    res = compare_daily_returns(yf, al)
    assert res["n_days"] == 500
    assert res["median_abs_diff_bps"] == 0.0
    assert res["p99_abs_diff_bps"] == 0.0
    assert res["passed"] is True


def test_single_outlier_passes_and_p99_is_the_independent_quantile():
    # One 50 bps spike in 500 days: a p99 cannot carry it (lead decision on AC 1).
    def spike(r):
        r[250] += 0.005

    yf, al = _pair(spike)
    res = compare_daily_returns(yf, al)
    diffs = (al.pct_change() - yf.pct_change()).abs().dropna() * 10_000
    assert res["median_abs_diff_bps"] < 1
    assert res["p99_abs_diff_bps"] == pytest.approx(float(np.quantile(diffs, 0.99)))
    assert res["p99_abs_diff_bps"] == pytest.approx(0.0, abs=1e-6)
    assert res["passed"] is True


def test_ten_outliers_show_in_p99_and_fail():
    def spikes(r):
        r[100:110] += 0.005

    yf, al = _pair(spikes)
    res = compare_daily_returns(yf, al)
    assert res["median_abs_diff_bps"] < 1
    assert res["p99_abs_diff_bps"] == pytest.approx(50.0, abs=0.01)
    assert res["passed"] is False


def test_constant_two_bps_offset_fails_via_the_median():
    def offset(r):
        r += 0.0002

    yf, al = _pair(offset)
    res = compare_daily_returns(yf, al)
    assert res["median_abs_diff_bps"] == pytest.approx(2.0, abs=0.01)
    assert res["p99_abs_diff_bps"] == pytest.approx(2.0, abs=0.01)
    assert res["p99_abs_diff_bps"] < P99_ABS_DIFF_BPS_MAX
    assert res["passed"] is False


# -- threshold boundaries ---------------------------------------------------


def test_thresholds_are_pinned():
    assert MEDIAN_ABS_DIFF_BPS_MAX == 1.0
    assert P99_ABS_DIFF_BPS_MAX == 10.0


@pytest.mark.parametrize("offset_bps,expected", [(0.9, True), (1.1, False)])
def test_median_threshold_boundary(offset_bps, expected):
    def offset(r):
        r += offset_bps / 10_000

    yf, al = _pair(offset)
    assert compare_daily_returns(yf, al)["passed"] is expected


@pytest.mark.parametrize("spike_bps,expected", [(9.5, True), (10.5, False)])
def test_p99_threshold_boundary(spike_bps, expected):
    def spikes(r):
        r[100:110] += spike_bps / 10_000

    yf, al = _pair(spikes)
    res = compare_daily_returns(yf, al)
    assert res["median_abs_diff_bps"] < MEDIAN_ABS_DIFF_BPS_MAX
    assert res["passed"] is expected


# -- alignment --------------------------------------------------------------


def test_alpaca_missing_days_shrink_n_days_without_false_diffs():
    yf, al = _pair()
    al = al.drop(al.index[list(range(50, 100, 5))])
    res = compare_daily_returns(yf, al)
    assert res["n_days"] == 490
    assert res["median_abs_diff_bps"] == 0.0
    assert res["p99_abs_diff_bps"] == pytest.approx(0.0, abs=1e-9)
    assert res["passed"] is True


def test_yfinance_missing_days_shrink_n_days_without_false_diffs():
    yf, al = _pair()
    yf = yf.drop(yf.index[list(range(50, 100, 5))])
    res = compare_daily_returns(yf, al)
    assert res["n_days"] == 490
    assert res["p99_abs_diff_bps"] == pytest.approx(0.0, abs=1e-9)
    assert res["passed"] is True


@pytest.mark.parametrize("case", ["empty", "no_overlap"])
def test_no_overlap_fails_closed(case):
    yf, al = _pair()
    if case == "empty":
        al = al.iloc[0:0]
    else:
        al = pd.Series(al.values, index=al.index + pd.Timedelta(days=3650))
    res = compare_daily_returns(yf, al)
    assert res["n_days"] == 0
    assert math.isnan(res["median_abs_diff_bps"])
    assert math.isnan(res["p99_abs_diff_bps"])
    assert res["passed"] is False


def test_tz_aware_index_raises():
    yf, al = _pair()
    al.index = al.index.tz_localize("UTC")
    with pytest.raises(ValueError):
        compare_daily_returns(yf, al)


def test_duplicated_index_raises():
    yf, al = _pair()
    al = pd.concat([al, al.iloc[[10]]]).sort_index()
    with pytest.raises(ValueError):
        compare_daily_returns(yf, al)


def test_result_types_are_plain_python():
    yf, al = _pair()
    res = compare_daily_returns(yf, al)
    assert type(res["passed"]) is bool
    assert type(res["n_days"]) is int
    assert type(res["median_abs_diff_bps"]) is float
    assert type(res["p99_abs_diff_bps"]) is float


# -- driver -----------------------------------------------------------------


def _long_index() -> pd.DatetimeIndex:
    return pd.bdate_range("2018-01-02", "2023-12-29")


def _long_close() -> pd.Series:
    idx = _long_index()
    rets = np.random.default_rng(1).normal(0.0, 0.01, len(idx) - 1)
    return _closes(rets, idx)


def _expected_n_days(idx: pd.DatetimeIndex) -> int:
    in_window = int(((idx >= "2019-01-01") & (idx <= "2021-12-31")).sum())
    return in_window - 1


def test_driver_passes_exact_alpaca_arguments_and_slices_window():
    close = _long_close()
    calls = []

    def alpaca_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        df = _frame(close)
        df.index = df.index.tz_localize("UTC") + pd.Timedelta(hours=5)
        return df

    rows = run_parity(
        ["SPY"], yf_fetch=lambda t: _frame(close), alpaca_fetch=alpaca_fetch
    )
    assert calls == [
        (("SPY", "1Day", "2019-01-01", ALPACA_END), {"adjustment": "all"})
    ]
    assert ALPACA_END == "2021-12-31T23:59:59Z"
    (row,) = rows
    assert row["ticker"] == "SPY"
    assert row["n_days"] == _expected_n_days(close.index)
    assert row["n_yf"] == row["n_alpaca"] == row["n_days"] + 1
    assert row["error"] is None
    assert row["passed"] is True


@pytest.mark.parametrize("hours", [5, 4, 0])
def test_alpaca_utc_stamps_align_to_session_dates(hours):
    close = _long_close()

    def alpaca_fetch(*args, **kwargs):
        df = _frame(close)
        df.index = df.index.tz_localize("UTC") + pd.Timedelta(hours=hours)
        return df

    (row,) = run_parity(
        ["SPY"], yf_fetch=lambda t: _frame(close), alpaca_fetch=alpaca_fetch
    )
    assert row["n_days"] == _expected_n_days(close.index)
    assert row["passed"] is True


def test_driver_truncates_alpaca_side_to_development_window():
    close = _long_close()
    # Corrupt every post-window alpaca close: it must not influence the result.
    bad = close.copy()
    bad[bad.index > "2021-12-31"] *= 3.0
    (row,) = run_parity(
        ["SPY"],
        yf_fetch=lambda t: _frame(close),
        alpaca_fetch=lambda *a, **k: _frame(bad),
    )
    assert row["n_alpaca"] == row["n_yf"]
    assert row["passed"] is True


def test_failing_ticker_does_not_abort_the_others():
    close = _long_close()

    def alpaca_fetch(ticker, *args, **kwargs):
        if ticker == "BAD":
            raise RuntimeError("alpaca down")
        return _frame(close)

    rows = run_parity(
        ["BAD", "SPY"], yf_fetch=lambda t: _frame(close), alpaca_fetch=alpaca_fetch
    )
    assert [r["ticker"] for r in rows] == ["BAD", "SPY"]
    assert rows[0]["passed"] is False
    assert "alpaca down" in rows[0]["error"]
    assert rows[1]["passed"] is True
    assert rows[1]["error"] is None


def test_yfinance_failure_becomes_error_row():
    close = _long_close()

    def yf_fetch(ticker):
        raise RuntimeError(f"no data for {ticker}")

    (row,) = run_parity(
        ["SPY"], yf_fetch=yf_fetch, alpaca_fetch=lambda *a, **k: _frame(close)
    )
    assert row["passed"] is False
    assert "no data for SPY" in row["error"]


def test_default_wiring_uses_module_level_fetchers(monkeypatch):
    close = _long_close()
    seen = {"yf": [], "alpaca": []}

    def fake_yf(ticker):
        seen["yf"].append(ticker)
        return _frame(close)

    def fake_alpaca(ticker, *args, **kwargs):
        seen["alpaca"].append(ticker)
        return _frame(close)

    monkeypatch.setattr(etf_data, "_fetch_yfinance", fake_yf)
    monkeypatch.setattr(parity, "fetch_bars", fake_alpaca)
    (row,) = run_parity(["QQQ"])
    assert seen == {"yf": ["QQQ"], "alpaca": ["QQQ"]}
    assert row["passed"] is True


# -- format_row and main ----------------------------------------------------


def test_format_row_shows_verdict_and_error():
    ok = {
        "ticker": "SPY",
        "n_days": 755,
        "median_abs_diff_bps": 0.12,
        "p99_abs_diff_bps": 3.4,
        "passed": True,
        "n_yf": 756,
        "n_alpaca": 756,
        "error": None,
    }
    bad = dict(ok, passed=False, error="RuntimeError('boom')")
    assert "PASS" in format_row(ok) and "SPY" in format_row(ok)
    assert "FAIL" in format_row(bad) and "boom" in format_row(bad)


def _main_fakes():
    close = _long_close()
    wobble = close * np.where(np.arange(len(close)) % 2, 1.01, 1.0)
    alpaca = {"SPY": close, "QQQ": close, "XLE": wobble}
    return (
        lambda t: _frame(close),
        lambda t, *a, **k: _frame(alpaca[t]),
    )


def test_main_returns_zero_when_all_pass(capsys):
    yf_fetch, alpaca_fetch = _main_fakes()
    code = main(["--tickers", "SPY,QQQ"], yf_fetch=yf_fetch, alpaca_fetch=alpaca_fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("PASS") == 2
    assert "FAIL" not in out


def test_main_returns_one_when_any_ticker_fails(capsys):
    yf_fetch, alpaca_fetch = _main_fakes()
    code = main(["--tickers", "SPY,XLE"], yf_fetch=yf_fetch, alpaca_fetch=alpaca_fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert out.count("PASS") == 1
    assert out.count("FAIL") == 1


def test_main_requires_tickers():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_main_rejects_empty_ticker_list():
    with pytest.raises(SystemExit) as exc:
        main(["--tickers", " , "])
    assert exc.value.code == 2


def test_main_has_no_window_flags():
    with pytest.raises(SystemExit) as exc:
        main(["--tickers", "SPY", "--end", "2023-01-01"])
    assert exc.value.code == 2


def test_module_source_has_no_forbidden_references():
    src = inspect.getsource(parity)
    for needle in ("urllib", "/v2/", "paper-api", "anthropic", "openai"):
        assert needle not in src, needle
