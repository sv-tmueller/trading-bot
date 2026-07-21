"""Tests for backtest/run_live_divergence.py (#403).

All offline — no network. Synthetic Open/Close frames + synthetic CSVs via
tmp_path, monkeypatching backtest.run_live_divergence._fetch the same way
tests/test_walkforward.py monkeypatches backtest.walkforward._fetch.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import backtest.run_live_divergence as rld
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_price_df(
    n_days: int,
    start: str = "2026-01-02",
    start_price: float = 100.0,
    drift: float = 0.001,
) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n_days)
    prices = [start_price * (1 + drift) ** i for i in range(n_days)]
    return pd.DataFrame({"Open": prices, "Close": prices}, index=idx)


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    df.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# load_live_export
# ---------------------------------------------------------------------------

def test_load_live_export_round_trips_all_four_tables(tmp_path: Path):
    _write_csv(tmp_path / "equity_snapshots.csv", pd.DataFrame({
        "date": ["2026-06-05", "2026-06-08"],
        "equity_usd": [100000.0, 100500.5],
    }))
    _write_csv(tmp_path / "trades.csv", pd.DataFrame({
        "fill_time": ["2026-06-11T13:37:00Z"],
        "symbol": ["UPRO"],
        "side": ["BUY"],
        "qty": [7458],
        "fill_price": [133.0571],
        "reason": ["regime_flip_long"],
        "broker_order_id": ["abc-123"],
    }))
    _write_csv(tmp_path / "regime_state.csv", pd.DataFrame({
        "date": ["2026-06-05"],
        "spy_close": [741.67],
        "spy_sma200": [684.03],
        "target_state": ["LONG"],
        "current_state": ["CASH"],
        "kill_switch_active": [False],
    }))
    _write_csv(tmp_path / "audit_log.csv", pd.DataFrame({
        "started_at": ["2026-06-05T13:37:00Z"],
        "finished_at": ["2026-06-05T13:37:05Z"],
        "outcome": ["success"],
        "notes": [""],
    }))

    data = rld.load_live_export(tmp_path)

    assert set(data.keys()) == {"equity_snapshots", "trades", "regime_state", "audit_log"}
    assert len(data["equity_snapshots"]) == 2
    assert data["equity_snapshots"]["equity_usd"].dtype.kind == "f"
    assert len(data["trades"]) == 1
    assert len(data["regime_state"]) == 1
    assert len(data["audit_log"]) == 1


def test_load_live_export_tolerates_empty_trades_csv(tmp_path: Path):
    _write_csv(tmp_path / "equity_snapshots.csv", pd.DataFrame({
        "date": ["2026-06-05"], "equity_usd": [100000.0],
    }))
    # Header-only trades.csv (no fills yet)
    (tmp_path / "trades.csv").write_text(
        "fill_time,symbol,side,qty,fill_price,reason,broker_order_id\n"
    )
    _write_csv(tmp_path / "regime_state.csv", pd.DataFrame({
        "date": ["2026-06-05"], "spy_close": [741.67], "spy_sma200": [684.03],
        "target_state": ["LONG"], "current_state": ["CASH"], "kill_switch_active": [False],
    }))
    # Completely empty audit_log.csv (0 bytes — no header at all)
    (tmp_path / "audit_log.csv").write_text("")

    data = rld.load_live_export(tmp_path)

    assert data["trades"].empty
    assert data["audit_log"].empty
    assert list(data["trades"].columns) == [
        "fill_time", "symbol", "side", "qty", "fill_price", "reason", "broker_order_id",
    ]


# ---------------------------------------------------------------------------
# replay_signal
# ---------------------------------------------------------------------------

def test_replay_signal_matches_strict_greater_than():
    prices = [100.0] * 210
    prices[209] = 200.0  # last close jumps well above its own SMA200
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)

    sig = rld.replay_signal(spy_df, sma_days=200)

    assert sig.dtype == bool
    assert sig.iloc[209] == True  # noqa: E712 — 200 > sma(~100) strictly
    assert sig.iloc[100] == False  # flat series: Close == SMA, strict > is False


def test_replay_signal_fills_warmup_nan_as_false():
    prices = [100.0 + i for i in range(50)]
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)

    sig = rld.replay_signal(spy_df, sma_days=200)

    # Fewer than 200 days of history -> rolling mean is NaN everywhere -> all False
    assert not sig.any()


# ---------------------------------------------------------------------------
# compute_tracking
# ---------------------------------------------------------------------------

def test_compute_tracking_zero_gap_when_curves_identical():
    idx = pd.bdate_range("2026-01-02", periods=10)
    curve = pd.Series([100_000.0 * (1.001 ** i) for i in range(10)], index=idx)
    live_snap = pd.DataFrame({"date": idx, "equity_usd": curve.values})

    result = rld.compute_tracking(live_snap, curve)

    assert result["n_days"] == 10
    assert result["terminal_return_diff"] == pytest.approx(0.0, abs=1e-9)
    assert result["terminal_equity_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert result["mean_abs_daily_gap"] == pytest.approx(0.0, abs=1e-9)
    assert result["max_abs_daily_gap"] == pytest.approx(0.0, abs=1e-9)


def test_compute_tracking_nonzero_gap_when_live_lags():
    idx = pd.bdate_range("2026-01-02", periods=10)
    sim_curve = pd.Series([100_000.0 * (1.01 ** i) for i in range(10)], index=idx)
    # Live grows more slowly -> live underperforms sim
    live_curve = pd.Series([100_000.0 * (1.005 ** i) for i in range(10)], index=idx)
    live_snap = pd.DataFrame({"date": idx, "equity_usd": live_curve.values})

    result = rld.compute_tracking(live_snap, sim_curve)

    assert result["terminal_return_diff"] < 0
    assert result["terminal_equity_ratio"] < 1.0
    assert result["max_abs_daily_gap"] > 0


def test_compute_tracking_cash_normalized_variant_zero_for_perfect_parity():
    """When both series are supplied with the shared starting_cash and track
    identically, both the close-normalized and cash-normalized terminal-diff
    variants read ~0 (#403 finding 1)."""
    idx = pd.bdate_range("2026-01-02", periods=10)
    curve = pd.Series([100_000.0 * (1.001 ** i) for i in range(10)], index=idx)
    live_snap = pd.DataFrame({"date": idx, "equity_usd": curve.values})

    result = rld.compute_tracking(live_snap, curve, starting_cash=100_000.0)

    assert result["terminal_return_diff"] == pytest.approx(0.0, abs=1e-9)
    assert result["terminal_return_diff_cash_normalized"] == pytest.approx(0.0, abs=1e-9)


def test_compute_tracking_cash_normalized_reveals_day1_loss_hidden_by_close_normalization():
    """Reproduces the #403 finding-1 artifact: compute_tracking's close
    normalization uses each curve's own first-common-date value as its 100%
    baseline. If the sim's tracking window already opens post-loss (e.g. a
    pre-roll trade executed and lost value before this window's first date,
    as happens with the go-live-ramp Trap-A restart), that loss is baked into
    the sim's own baseline and the close-normalized terminal_return_diff is
    blind to it -- even though live (which never traded) is flat the whole
    time. The cash-normalized variant, anchored to the *shared* starting_cash
    instead of each curve's own first value, reveals the loss exactly.
    """
    starting_cash = 100_000.0
    loss = 0.063  # 6.3% day-1 open-to-close loss, matching the real report
    idx = pd.bdate_range("2026-06-05", periods=5)

    # The sim's first tracking-window value already embeds the day-1 loss.
    sim = pd.Series([starting_cash * (1 - loss)] * len(idx), index=idx)

    # Live stayed in cash (no fill yet) for the whole window.
    live_snap = pd.DataFrame({"date": idx, "equity_usd": [starting_cash] * len(idx)})

    result = rld.compute_tracking(live_snap, sim, starting_cash=starting_cash)

    assert result["terminal_return_diff"] == pytest.approx(0.0, abs=1e-9)
    assert result["terminal_return_diff_cash_normalized"] == pytest.approx(loss, abs=1e-9)
    # The two variants diverge by exactly the hidden day-1 loss.
    diff = result["terminal_return_diff_cash_normalized"] - result["terminal_return_diff"]
    assert diff == pytest.approx(loss, abs=1e-9)


# ---------------------------------------------------------------------------
# compute_fill_slippage
# ---------------------------------------------------------------------------

def test_compute_fill_slippage_buy_convention():
    """BUY filled above the day's open is a positive (cost) slippage."""
    vehicle_df = _make_price_df(n_days=3, drift=0.0)
    fill_date = vehicle_df.index[0]
    open_px = float(vehicle_df["Open"].iloc[0])
    fill_price = open_px * 1.0010  # 10 bps worse than open for a BUY

    trades_df = pd.DataFrame({
        "fill_time": [fill_date.isoformat()],
        "symbol": ["UPRO"], "side": ["BUY"], "qty": [100],
        "fill_price": [fill_price], "reason": ["regime_flip_long"],
        "broker_order_id": ["o1"],
    })

    result = rld.compute_fill_slippage(trades_df, vehicle_df)

    assert len(result) == 1
    assert result["cost_bps"].iloc[0] == pytest.approx(10.0, abs=1e-6)
    assert result["delta_vs_slippage_bps"].iloc[0] == pytest.approx(10.0 - SLIPPAGE_BPS)
    assert result["delta_vs_total_bps"].iloc[0] == pytest.approx(
        10.0 - (SLIPPAGE_BPS + COMMISSION_BPS)
    )


def test_compute_fill_slippage_sell_convention():
    """SELL filled below the day's open is a positive (cost) slippage."""
    vehicle_df = _make_price_df(n_days=3, drift=0.0)
    fill_date = vehicle_df.index[0]
    open_px = float(vehicle_df["Open"].iloc[0])
    fill_price = open_px * 0.9990  # 10 bps worse than open for a SELL

    trades_df = pd.DataFrame({
        "fill_time": [fill_date.isoformat()],
        "symbol": ["UPRO"], "side": ["SELL"], "qty": [100],
        "fill_price": [fill_price], "reason": ["regime_flip_cash"],
        "broker_order_id": ["o2"],
    })

    result = rld.compute_fill_slippage(trades_df, vehicle_df)

    assert len(result) == 1
    assert result["cost_bps"].iloc[0] == pytest.approx(10.0, abs=1e-6)


def test_compute_fill_slippage_empty_trades_returns_empty_frame():
    vehicle_df = _make_price_df(n_days=3)
    trades_df = pd.DataFrame(columns=[
        "fill_time", "symbol", "side", "qty", "fill_price", "reason", "broker_order_id",
    ])

    result = rld.compute_fill_slippage(trades_df, vehicle_df)

    assert result.empty


# ---------------------------------------------------------------------------
# compute_divergence_dates
# ---------------------------------------------------------------------------

def test_compute_divergence_dates_flags_signal_mismatch():
    """A recorded target_state contradicting the synthetic signal is flagged."""
    prices = [100.0] * 210
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)
    signal = rld.replay_signal(spy_df, sma_days=200)  # all False (flat series)

    row_date = idx[205]
    regime_state_df = pd.DataFrame({
        "date": [row_date],
        "spy_close": [100.0],
        "spy_sma200": [100.0],
        "target_state": ["LONG"],  # contradicts the (False) replayed signal
        "current_state": ["LONG"],
        "kill_switch_active": [False],
    })
    audit_df = pd.DataFrame(columns=["started_at", "finished_at", "outcome", "notes"])

    result = rld.compute_divergence_dates(regime_state_df, signal, audit_df)

    assert len(result) == 1
    assert bool(result["signal_mismatch"].iloc[0]) is True
    assert result["replayed_target"].iloc[0] == "CASH"


def test_compute_divergence_dates_no_mismatch_when_parity_holds():
    prices = [100.0] * 210
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)
    signal = rld.replay_signal(spy_df, sma_days=200)  # all False (flat series)

    row_date = idx[205]
    regime_state_df = pd.DataFrame({
        "date": [row_date],
        "spy_close": [100.0], "spy_sma200": [100.0],
        "target_state": ["CASH"], "current_state": ["CASH"],
        "kill_switch_active": [False],
    })
    audit_df = pd.DataFrame(columns=["started_at", "finished_at", "outcome", "notes"])

    result = rld.compute_divergence_dates(regime_state_df, signal, audit_df)

    assert bool(result["signal_mismatch"].iloc[0]) is False
    assert bool(result["execution_mismatch"].iloc[0]) is False


def test_compute_divergence_dates_flags_execution_mismatch_and_attaches_audit():
    """current_state disagreeing with the replayed position is execution parity,
    and the matching audit_log outcome/notes are attached by date."""
    prices = [100.0] * 210
    prices[209] = 200.0  # day index 209 close jumps bullish
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)
    signal = rld.replay_signal(spy_df, sma_days=200)

    row_date = idx[210] if len(idx) > 210 else idx[209] + pd.offsets.BDay(1)
    regime_state_df = pd.DataFrame({
        "date": [row_date],
        "spy_close": [200.0], "spy_sma200": [100.0],
        "target_state": ["LONG"],   # signal parity holds (matches replayed)
        "current_state": ["CASH"],  # but the live bot hasn't executed yet
        "kill_switch_active": [False],
    })
    audit_df = pd.DataFrame({
        "started_at": [row_date.isoformat()],
        "finished_at": [row_date.isoformat()],
        "outcome": ["skipped:trading_paused"],
        "notes": ["manual pause"],
    })

    result = rld.compute_divergence_dates(regime_state_df, signal, audit_df)

    assert bool(result["signal_mismatch"].iloc[0]) is False
    assert bool(result["execution_mismatch"].iloc[0]) is True
    assert result["outcome"].iloc[0] == "skipped:trading_paused"
    assert result["notes"].iloc[0] == "manual pause"


def test_compute_divergence_dates_aggregates_same_day_audit_rows():
    """Two daily-check invocations on the same trading day (13:37 + 14:37 UTC
    cron slots) with differing outcomes both survive in the attached
    outcome/notes columns -- a same-day join must not silently drop the
    earlier row's outcome (#403 finding 3)."""
    prices = [100.0] * 210
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)
    signal = rld.replay_signal(spy_df, sma_days=200)  # all False (flat series)

    row_date = idx[205]
    regime_state_df = pd.DataFrame({
        "date": [row_date],
        "spy_close": [100.0], "spy_sma200": [100.0],
        "target_state": ["CASH"], "current_state": ["CASH"],
        "kill_switch_active": [False],
    })
    audit_df = pd.DataFrame({
        "started_at": [
            row_date + pd.Timedelta(hours=13, minutes=37),
            row_date + pd.Timedelta(hours=14, minutes=37),
        ],
        "finished_at": [
            row_date + pd.Timedelta(hours=13, minutes=37, seconds=5),
            row_date + pd.Timedelta(hours=14, minutes=37, seconds=5),
        ],
        "outcome": ["error:OrderTimeoutError", "success"],
        "notes": ["", "no-op re-run"],
    })

    result = rld.compute_divergence_dates(regime_state_df, signal, audit_df)

    assert len(result) == 1
    outcome = result["outcome"].iloc[0]
    assert "error:OrderTimeoutError" in outcome
    assert "success" in outcome
    assert result["notes"].iloc[0] == "no-op re-run"


def test_compute_divergence_dates_reports_data_drift_when_benchmark_given():
    prices = [100.0] * 210
    idx = pd.bdate_range("2025-01-02", periods=len(prices))
    spy_df = pd.DataFrame({"Open": prices, "Close": prices}, index=idx)
    signal = rld.replay_signal(spy_df, sma_days=200)

    row_date = idx[205]
    # Recorded spy_close is 1% off the yfinance value at the same prior day
    regime_state_df = pd.DataFrame({
        "date": [row_date],
        "spy_close": [101.0], "spy_sma200": [100.0],
        "target_state": ["CASH"], "current_state": ["CASH"],
        "kill_switch_active": [False],
    })
    audit_df = pd.DataFrame(columns=["started_at", "finished_at", "outcome", "notes"])

    result = rld.compute_divergence_dates(
        regime_state_df, signal, audit_df, benchmark_close=spy_df["Close"], sma_days=200,
    )

    assert result["spy_close_diff_pct"].iloc[0] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# run_report / main (offline, monkeypatched _fetch)
# ---------------------------------------------------------------------------

def _write_full_export(tmp_path: Path, sim_equity: pd.Series, first_fill_date, fill_price: float) -> None:
    _write_csv(tmp_path / "equity_snapshots.csv", pd.DataFrame({
        "date": sim_equity.index,
        "equity_usd": sim_equity.values,
    }))
    _write_csv(tmp_path / "trades.csv", pd.DataFrame({
        "fill_time": [first_fill_date.isoformat()],
        "symbol": ["UPRO"], "side": ["BUY"], "qty": [100],
        "fill_price": [fill_price], "reason": ["regime_flip_long"],
        "broker_order_id": ["o1"],
    }))
    _write_csv(tmp_path / "regime_state.csv", pd.DataFrame({
        "date": [sim_equity.index[0]],
        "spy_close": [100.0], "spy_sma200": [100.0],
        "target_state": ["LONG"], "current_state": ["LONG"],
        "kill_switch_active": [False],
    }))
    (tmp_path / "audit_log.csv").write_text("")


def test_run_report_perfect_parity_zero_tracking_error(tmp_path: Path, monkeypatch):
    """Live snapshots generated from the sim's own curve -> ~zero tracking error,
    zero divergence dates, realized fill cost matching the modeled convention."""
    benchmark_df = _make_price_df(n_days=260, drift=0.0006)
    vehicle_df = _make_price_df(n_days=260, drift=0.0006)

    monkeypatch.setattr(
        rld, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    signal = rld.replay_signal(benchmark_df, sma_days=200)
    sim = simulate_from_signal(
        vehicle_df=vehicle_df, is_bullish_close_t=signal,
        starting_cash=100_000.0, slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )
    eq = sim["equity_curve"]
    # Window must start the day *before* the position is first entered (still
    # 100% cash, matching D3's "starting_cash = earliest snapshot" anchor,
    # which assumes the earliest snapshot predates the first trade — true of
    # the real deploy history, #386/#391). run_report's Trap-A restart (fresh
    # cash, 1-day pre-roll) then re-executes that same first buy on day 2 of
    # the window, so the two curves are directly comparable. A window
    # starting mid-holding-period (or exactly on the entry day, which would
    # already carry a post-trade equity value into Trap-A's fresh
    # starting_cash and double-count that day's slippage/commission) would
    # be an artifact of the Trap-A methodology rather than a real divergence.
    first_trade = sim["trades"][0]
    entry_date = first_trade["entry_date"]
    window = eq.loc[eq.index >= (entry_date - pd.offsets.BDay(1))]
    pre_entry_date = window.index[0]

    fill_open = float(vehicle_df.loc[entry_date, "Open"])
    fill_price = fill_open * (1 + SLIPPAGE_BPS / 10_000)  # exact modeled fill

    _write_csv(tmp_path / "equity_snapshots.csv", pd.DataFrame({
        "date": window.index, "equity_usd": window.values,
    }))
    _write_csv(tmp_path / "trades.csv", pd.DataFrame({
        "fill_time": [entry_date.isoformat()],
        "symbol": ["UPRO"], "side": ["BUY"], "qty": [100],
        "fill_price": [fill_price], "reason": ["regime_flip_long"],
        "broker_order_id": ["o1"],
    }))
    _write_csv(tmp_path / "regime_state.csv", pd.DataFrame({
        "date": [pre_entry_date, entry_date],
        "spy_close": [100.0, 100.0], "spy_sma200": [100.0, 100.0],
        "target_state": ["CASH", "LONG"], "current_state": ["CASH", "LONG"],
        "kill_switch_active": [False, False],
    }))
    (tmp_path / "audit_log.csv").write_text("")

    report = rld.run_report(export_dir=tmp_path, benchmark="SPY", vehicle="UPRO", sma_days=200)

    assert report["tracking_full"]["terminal_return_diff"] == pytest.approx(0.0, abs=1e-6)
    assert report["tracking_full"]["terminal_equity_ratio"] == pytest.approx(1.0, abs=1e-6)
    assert report["tracking_full"]["terminal_return_diff_cash_normalized"] == pytest.approx(
        0.0, abs=1e-6
    )
    assert report["divergence"]["signal_mismatch"].sum() == 0
    assert report["divergence"]["execution_mismatch"].sum() == 0
    assert report["fill_slippage"]["delta_vs_slippage_bps"].iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_run_report_late_entry_shows_execution_divergence_and_tracking_gap(tmp_path: Path, monkeypatch):
    """Live enters N days after the simulated open -> execution-parity divergence
    dates for the lag window and a nonzero tracking gap."""
    benchmark_df = _make_price_df(n_days=260, drift=0.0008)
    vehicle_df = _make_price_df(n_days=260, drift=0.0008)

    monkeypatch.setattr(
        rld, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    signal = rld.replay_signal(benchmark_df, sma_days=200)
    sim = simulate_from_signal(
        vehicle_df=vehicle_df, is_bullish_close_t=signal,
        starting_cash=100_000.0, slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )
    eq = sim["equity_curve"]
    window = eq.iloc[-30:]

    # Live enters 3 trading days late: regime_state rows in the lag show
    # current_state=CASH while the replayed signal has already gone LONG.
    lag_days = 3
    late_fill_date = window.index[lag_days]
    late_fill_open = float(vehicle_df.loc[late_fill_date, "Open"])
    late_fill_price = late_fill_open * (1 + SLIPPAGE_BPS / 10_000)

    _write_csv(tmp_path / "equity_snapshots.csv", pd.DataFrame({
        "date": window.index, "equity_usd": window.values,
    }))
    _write_csv(tmp_path / "trades.csv", pd.DataFrame({
        "fill_time": [late_fill_date.isoformat()],
        "symbol": ["UPRO"], "side": ["BUY"], "qty": [100],
        "fill_price": [late_fill_price], "reason": ["regime_flip_long"],
        "broker_order_id": ["o1"],
    }))
    regime_rows = []
    for i, d in enumerate(window.index[: lag_days + 1]):
        regime_rows.append({
            "date": d, "spy_close": 100.0, "spy_sma200": 100.0,
            "target_state": "LONG",
            "current_state": "CASH" if i < lag_days else "LONG",
            "kill_switch_active": False,
        })
    _write_csv(tmp_path / "regime_state.csv", pd.DataFrame(regime_rows))
    (tmp_path / "audit_log.csv").write_text("")

    report = rld.run_report(export_dir=tmp_path, benchmark="SPY", vehicle="UPRO", sma_days=200)

    assert report["divergence"]["execution_mismatch"].sum() == lag_days
    assert report["tracking_full"]["max_abs_daily_gap"] > 0


def test_main_cli_offline(tmp_path: Path, monkeypatch, capsys):
    benchmark_df = _make_price_df(n_days=260, drift=0.0005)
    vehicle_df = _make_price_df(n_days=260, drift=0.0005)

    monkeypatch.setattr(
        rld, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    signal = rld.replay_signal(benchmark_df, sma_days=200)
    sim = simulate_from_signal(
        vehicle_df=vehicle_df, is_bullish_close_t=signal,
        starting_cash=100_000.0, slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )
    window = sim["equity_curve"].iloc[-20:]
    fill_date = window.index[0]
    fill_price = float(vehicle_df.loc[fill_date, "Open"]) * (1 + SLIPPAGE_BPS / 10_000)
    _write_full_export(tmp_path, window, fill_date, fill_price)

    rc = rld.main(["--export-dir", str(tmp_path), "--benchmark", "SPY", "--vehicle", "UPRO"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Tracking" in captured.out or "tracking" in captured.out.lower()
