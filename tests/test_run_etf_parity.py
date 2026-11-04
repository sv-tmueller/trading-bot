"""Offline tests for the yfinance vs Alpaca daily parity check."""
from __future__ import annotations

import inspect
import math
from datetime import date
import warnings

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
        pytest.fail("unmocked network/Alpaca call")

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
    assert res["fail_reasons"] == []
    assert res["n_gated"] + res["n_suspect"] == 500
    assert res["gated_median_abs_diff_bps"] == 0.0
    assert res["gated_mean_diff_bps"] == 0.0
    assert res["n_gated_over"] == res["n_suspect_over"] == 0


def test_single_outlier_passes_and_p99_is_the_independent_quantile():
    # One 50 bps spike in 500 days: a p99 cannot carry it (lead decision on AC 1).
    def spike(r):
        r[250] += 0.005

    yf, al = _pair(spike)
    res = compare_daily_returns(yf, al)
    diffs = (al.pct_change() - yf.pct_change()).abs().dropna() * 10_000
    assert res["n_days"] == 500
    assert float(diffs.max()) == pytest.approx(50.0, abs=0.01)
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
    # Closes scaled by 1e4 make the one-cent allowance negligible, so this
    # still pins the 1 bp floor.
    def offset(r):
        r += offset_bps / 10_000

    yf, al = _pair(offset)
    res = compare_daily_returns(yf * 1e4, al * 1e4)
    assert res["median_max_bps"] == pytest.approx(1.0, abs=1e-3)
    assert res["passed"] is expected


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


def test_non_leading_nan_close_counts_as_one_missing_day():
    # A NaN close must shrink n_days by one (501 bars -> 500 returns -> 499),
    # never be padded into a fabricated zero return plus a two-day return.
    yf, al = _pair()
    al.iloc[100] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        res = compare_daily_returns(yf, al)
    assert res["n_days"] == 499
    assert res["median_abs_diff_bps"] == 0.0
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
    assert res["n_gated"] == 0
    assert res["fail_reasons"] == ["no_data"]
    assert res["worst_gated"] == [] and res["worst_suspect"] == []


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
    for key in ("n_gated", "n_gated_over", "n_suspect", "n_suspect_over"):
        assert type(res[key]) is int, key
    for key in (
        "gated_median_abs_diff_bps",
        "gated_p99_abs_diff_bps",
        "gated_mean_diff_bps",
        "median_max_bps",
    ):
        assert type(res[key]) is float, key
    assert type(res["fail_reasons"]) is list
    for key in ("worst_gated", "worst_suspect"):
        assert type(res[key]) is list
        for d, diff, yf_close, al_close in res[key]:
            assert type(d) is str
            assert type(diff) is float
            assert type(yf_close) is float and type(al_close) is float


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


_HEADER_TEXT = (
    "ticker    n_days  median_bps   p99_bps   n_yf  n_alpaca  n_gated  gated_med  "
    "gated_p99  med_max  mean_bps verdict"
)


def _ok_row():
    return {
        "ticker": "SPY",
        "n_days": 756,
        "median_abs_diff_bps": 1.41,
        "p99_abs_diff_bps": 37.866,
        "passed": True,
        "n_yf": 757,
        "n_alpaca": 757,
        "n_gated": 707,
        "gated_median_abs_diff_bps": 0.35,
        "gated_p99_abs_diff_bps": 4.1,
        "gated_mean_diff_bps": -0.093,
        "median_max_bps": 1.101,
        "n_gated_over": 0,
        "n_suspect": 49,
        "n_suspect_over": 31,
        "worst_gated": [("2019-06-21", 8.5, 100.1234, 100.2085)],
        "worst_suspect": [("2020-03-13", 268.83, 244.8822, 245.67)],
        "fail_reasons": [],
        "error": None,
    }


def test_format_row_shows_verdict_and_error():
    ok = _ok_row()
    bad = dict(ok, passed=False, error="RuntimeError('boom')")
    assert "PASS" in format_row(ok) and "SPY" in format_row(ok)
    assert "FAIL" in format_row(bad) and "boom" in format_row(bad)


def test_format_row_columns_and_fail_reasons():
    ok = _ok_row()
    assert format_row(ok) == (
        "SPY          756       1.410    37.866    757       757      707      0.350"
        "      4.100    1.101    -0.093 PASS"
    )
    both = dict(ok, passed=False, fail_reasons=["median", "p99"])
    assert format_row(both).endswith(" FAIL median+p99")
    no_data = dict(ok, passed=False, fail_reasons=["no_data"])
    assert format_row(no_data).endswith(" FAIL no_data")
    err = dict(ok, passed=False, error="RuntimeError('boom')")
    assert format_row(err).endswith(" FAIL  RuntimeError('boom')")


def test_format_sessions_block_layout():
    lines = parity.format_sessions(_ok_row())
    assert lines == [
        "SPY suspect window 2020-02-24..2020-04-30 (not gated): 49 days, 31 >= 10 bps",
        "  2020-03-13  |diff|  268.830 bps  yf 244.8822  alpaca 245.6700  suspect",
        "SPY gated: 707 days, 0 >= 10 bps",
        "  2019-06-21  |diff|    8.500 bps  yf 100.1234  alpaca 100.2085  gated",
    ]
    assert not any("PASS" in ln or "FAIL" in ln for ln in lines)


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


def _march_fakes():
    close = _long_close()
    idx = close.index

    def with_ratios(dates):
        s = close.copy()
        for d, ratio in zip(dates, _BAD_RATIOS):
            s[pd.Timestamp(d)] *= ratio
        return s

    alpaca = {
        "SPY": close,
        "MAR": with_ratios(_BAD_IN_WINDOW),
        "P99": with_ratios(_BAD_OUT_OF_WINDOW),
    }
    assert all(s.index.equals(idx) for s in alpaca.values())
    return (
        lambda t: _frame(close),
        lambda t, *a, **k: _frame(alpaca[t]),
    )


def test_main_prints_header_sessions_and_reasons(capsys):
    yf_fetch, alpaca_fetch = _march_fakes()
    code = main(
        ["--tickers", "SPY,MAR,P99"], yf_fetch=yf_fetch, alpaca_fetch=alpaca_fetch
    )
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert code == 1
    assert lines[0] == _HEADER_TEXT
    assert any(ln.startswith("P99 ") and ln.endswith(" FAIL p99") for ln in lines)
    assert out.count("PASS") + out.count("FAIL") == 3
    assert "MAR suspect window 2020-02-24..2020-04-30 (not gated): " in out
    suspect_lines = [ln for ln in lines if ln.endswith("suspect")]
    assert any(ln.startswith("  2020-03-12  |diff|") for ln in suspect_lines)
    assert any(ln.startswith("  2020-03-16  |diff|") for ln in suspect_lines)
    # one blank line before each of the three blocks
    assert lines.count("") == 3


def test_error_rows_print_no_session_block(capsys):
    close = _long_close()

    def alpaca_fetch(ticker, *args, **kwargs):
        if ticker == "BAD":
            raise RuntimeError("alpaca down")
        return _frame(close)

    code = main(
        ["--tickers", "BAD,SPY"],
        yf_fetch=lambda t: _frame(close),
        alpaca_fetch=alpaca_fetch,
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "alpaca down" in out
    assert "BAD suspect window" not in out and "BAD gated" not in out
    assert "SPY suspect window" in out and "SPY gated" in out
    assert out.count("PASS") + out.count("FAIL") == 2


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


# -- suspect window (#757) --------------------------------------------------

# Alpaca/official close ratios from the #754 diagnostic (March 2020 sessions).
_BAD_RATIOS = [
    251.23 / 249.3468,
    232.07 / 225.5969,
    91.18 / 95.23,
    214.29 / 218.2228,
    221.32 / 222.3870,
]
_BAD_IN_WINDOW = ["2020-03-09", "2020-03-12", "2020-03-16", "2020-03-18", "2020-03-24"]
_BAD_OUT_OF_WINDOW = ["2019-03-11", "2019-03-14", "2019-03-18", "2019-03-20", "2019-03-26"]


def _frozen_pair(bad_dates, ratios=None):
    """Identical closes except Alpaca is multiplied by a ratio on bad_dates."""
    idx = pd.bdate_range("2019-01-02", "2021-12-31")
    rets = np.random.default_rng(2).normal(0.0, 0.01, len(idx) - 1)
    yf = _closes(rets, idx)
    al = yf.copy()
    for d, ratio in zip(bad_dates, _BAD_RATIOS if ratios is None else ratios):
        al[pd.Timestamp(d)] *= ratio
    return yf, al


def test_suspect_window_constants_are_pinned():
    assert parity.SUSPECT_WINDOW_START == date(2020, 2, 24)
    assert parity.SUSPECT_WINDOW_END == date(2020, 4, 30)
    assert parity.WORST_SESSIONS_N == 5
    assert (
        parity.WINDOW_START
        <= parity.SUSPECT_WINDOW_START
        <= parity.SUSPECT_WINDOW_END
        <= etf_data.DEV_END
    )


def test_march_2020_bad_closes_are_flagged_not_gated():
    yf, al = _frozen_pair(_BAD_IN_WINDOW)
    res = compare_daily_returns(yf, al)
    assert res["p99_abs_diff_bps"] >= P99_ABS_DIFF_BPS_MAX  # the old gate fails
    assert res["gated_p99_abs_diff_bps"] == 0.0
    assert res["passed"] is True
    assert res["fail_reasons"] == []
    assert res["n_suspect_over"] == 10
    assert res["n_gated_over"] == 0
    in_window = (yf.index >= "2020-02-24") & (yf.index <= "2020-04-30")
    assert res["n_suspect"] == int(in_window.sum()) + 1  # plus the 2020-05-01 return
    assert res["n_suspect"] == 50
    assert res["n_gated"] == res["n_days"] - 50
    dates = [w[0] for w in res["worst_suspect"]]
    assert len(dates) == 5
    assert "2020-03-12" in dates and "2020-03-16" in dates
    assert res["worst_gated"][0][1] == 0.0


def test_same_bad_closes_outside_the_window_still_fail_p99():
    yf, al = _frozen_pair(_BAD_OUT_OF_WINDOW)
    res = compare_daily_returns(yf, al)
    assert res["n_gated_over"] == 10
    assert res["n_suspect_over"] == 0
    assert res["passed"] is False
    assert res["fail_reasons"] == ["p99"]


def test_window_edge_before_start_gates_one_day_and_suspects_the_next():
    yf, al = _frozen_pair(["2020-02-21"], [1.02])
    res = compare_daily_returns(yf, al)
    assert [w[0] for w in res["worst_gated"][:1]] == ["2020-02-21"]
    assert res["n_gated_over"] == 1
    assert res["n_suspect_over"] == 1
    assert [w[0] for w in res["worst_suspect"][:1]] == ["2020-02-24"]


def test_window_edge_at_end_makes_both_adjacent_returns_suspect():
    yf, al = _frozen_pair(["2020-04-30"], [1.02])
    res = compare_daily_returns(yf, al)
    assert res["n_gated_over"] == 0
    assert res["n_suspect_over"] == 2
    assert {w[0] for w in res["worst_suspect"][:2]} == {"2020-04-30", "2020-05-01"}


# -- cent-rounding allowance on the median (#757) ---------------------------


def _level_pair(price: float):
    """yf closes iid around `price`; Alpaca closes are the same rounded to cents."""
    idx = pd.bdate_range("2019-01-02", "2021-12-31")
    noise = np.random.default_rng(3).normal(0.0, 0.01, len(idx))
    yf = pd.Series(price * (1.0 + noise), index=idx)
    return yf, yf.round(2)


def _scaled_pair(median_price: float, offset_bps: float):
    """_pair with a constant return offset, closes rescaled to a given median price."""

    def offset(r):
        r += offset_bps / 10_000

    yf, al = _pair(offset)
    k = median_price / float(yf.median())
    return yf * k, al * k


def test_cent_rounding_constants_are_pinned():
    assert parity.ONE_CENT == 0.01
    assert parity.CENT_ROUNDING_MEDIAN_FACTOR == pytest.approx(1 - 1 / math.sqrt(2))


def test_median_max_bps_is_floor_plus_cent_allowance():
    yf, al = _level_pair(21.0)
    res = compare_daily_returns(yf, al)
    expected = 1.0 + (1 - 1 / math.sqrt(2)) * (10_000 * 0.01 / float(yf.median()))
    assert res["median_max_bps"] == pytest.approx(expected)


@pytest.mark.parametrize("price", [21.0, 12.0])
def test_cent_rounding_on_low_priced_etf_is_not_a_failure(price):
    yf, al = _level_pair(price)
    res = compare_daily_returns(yf, al)
    assert res["median_abs_diff_bps"] >= 1.0  # the old gate fails on rounding alone
    assert res["gated_median_abs_diff_bps"] < res["median_max_bps"]
    assert res["passed"] is True
    assert res["fail_reasons"] == []


def test_constant_offset_at_high_price_still_fails_the_median():
    yf, al = _scaled_pair(290.0, 1.41)
    res = compare_daily_returns(yf, al)
    assert res["median_max_bps"] < 1.2
    assert res["passed"] is False
    assert res["fail_reasons"] == ["median"]


def test_cent_allowance_is_bounded_at_low_price():
    yf, al = _scaled_pair(21.0, 3.0)
    res = compare_daily_returns(yf, al)
    assert res["median_max_bps"] < 3.0
    assert res["passed"] is False
    assert res["fail_reasons"] == ["median"]


def test_worst_sessions_are_sorted_by_abs_diff_then_date():
    yf, al = _frozen_pair(_BAD_IN_WINDOW)
    worst = compare_daily_returns(yf, al)["worst_suspect"]
    keys = [(-w[1], w[0]) for w in worst]
    assert keys == sorted(keys)
    date_str, diff, yf_close, al_close = worst[0]
    assert isinstance(date_str, str) and len(date_str) == 10
    assert diff > 100.0
    assert yf_close > 0 and al_close > 0
