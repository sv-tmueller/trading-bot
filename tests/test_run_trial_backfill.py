"""Tests for backtest/run_trial_backfill.py (offline; no network, no real trials file).

The store is always a ``tmp_path`` copy of ``[]``; the committed
``docs/research/pipeline/trials.json`` is never touched. Every network entry point is blocked
by an autouse fixture, so a test that reaches yfinance fails loudly instead of fetching.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import backtest.etf_data as etf_data
import backtest.regime as regime
import backtest.run_candidate_survey as rcs
import backtest.run_trial_backfill as rtb
import backtest.tested_cells as tested_cells
import backtest.trial_store as trial_store
from backtest.overfitting_gate import deflated_sharpe_ratio

EXPECTED_IDS = {
    "backfill-tsmom-12m-spy",
    "backfill-faber-10m-spy",
    "backfill-faber-gtaa5",
    "backfill-gem-dual-momentum",
    "backfill-vol-target-10-spy",
}
REPO_ROOT = Path(__file__).resolve().parents[1]
BIL_START = pd.Timestamp("2012-03-01")


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def boom(*args, **kwargs):
        pytest.fail("network access attempted")

    monkeypatch.setattr(etf_data, "_fetch_yfinance", boom)
    monkeypatch.setattr(rcs, "_fetch", boom)
    monkeypatch.setattr(regime, "_fetch", boom, raising=False)
    import yfinance

    monkeypatch.setattr(yfinance, "download", boom)


def _make_frames(wild_after: bool = False) -> dict:
    idx = pd.bdate_range("2010-01-04", "2023-12-29")
    frames = {}
    drifts = {"SPY": 0.0004, "EFA": 0.0002, "AGG": 0.0001,
              "BIL": 0.00004, "DBC": 0.0001, "VNQ": 0.0003}
    for i, (ticker, drift) in enumerate(drifts.items()):
        r = np.random.default_rng(100 + i).normal(drift, 0.011, len(idx))
        px = 100.0 * np.exp(np.cumsum(r))
        if wild_after:
            wild = np.random.default_rng(900 + i).uniform(0.2, 5.0, len(idx))
            px = np.where(idx > pd.Timestamp("2021-12-31"), px * wild, px)
        frame = pd.DataFrame(
            {"Open": px, "High": px * 1.002, "Low": px * 0.998, "Close": px}, index=idx
        )
        if ticker == "BIL":
            frame = frame[frame.index >= BIL_START]
        frames[ticker] = frame
    return frames


class Fetcher:
    def __init__(self, frames: dict):
        self.frames = frames
        self.calls = 0

    def __call__(self, ticker: str) -> pd.DataFrame:
        self.calls += 1
        return self.frames[ticker].copy()


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text("[]\n", encoding="utf-8")
    return path


def _run(store, fetch, *extra):
    return rtb.main(["--path", str(store), *extra], fetch=fetch)


def test_configured_ids_are_the_five_expected_trials():
    assert len(rtb.TRIALS) == 5
    assert {t.trial_id for t in rtb.TRIALS} == EXPECTED_IDS


def test_each_trial_matches_one_ledger_record_with_same_source_and_date():
    for spec in rtb.TRIALS:
        hits = tested_cells.find(spec.ledger_family, "daily", spec.ledger_vehicle)
        assert len(hits) == 1, spec.trial_id
        assert hits[0].source == spec.source
        assert hits[0].date == rtb.TRIAL_DATE
        assert (REPO_ROOT / spec.source).is_file()


def test_dry_run_lists_ids_without_fetching_or_writing(store, capsys):
    fetch = Fetcher(_make_frames())
    before = store.read_bytes()
    assert _run(store, fetch, "--dry-run") == 0
    out = capsys.readouterr().out
    for trial_id in EXPECTED_IDS:
        assert trial_id in out
    assert out.count("missing") == 5
    assert fetch.calls == 0
    assert store.read_bytes() == before


def test_real_run_appends_five_records(store):
    fetch = Fetcher(_make_frames())
    assert _run(store, fetch) == 0
    records = trial_store.load_trials(store)
    assert {r.trial_id for r in records} == EXPECTED_IDS
    for r in records:
        assert r.round_id == trial_store.BACKFILL_ROUND
        assert r.space == trial_store.DAILY_ALLOCATION
        assert np.isfinite(r.sharpe_daily)
        assert r.n_periods >= 2
    sharpes = trial_store.programme_sharpes(path=store)
    assert sharpes.shape == (5,)
    assert sorted(sharpes) == sorted(r.sharpe_daily for r in records)


def test_rerun_is_a_noop_and_never_fetches(store, capsys):
    assert _run(store, Fetcher(_make_frames())) == 0
    before = store.read_bytes()
    capsys.readouterr()
    fetch = Fetcher(_make_frames())
    assert _run(store, fetch) == 0
    assert "nothing to append" in capsys.readouterr().out
    assert store.read_bytes() == before
    assert fetch.calls == 0


def test_partial_store_keeps_existing_records_and_adds_the_rest(store):
    existing = [
        trial_store.TrialRecord(
            trial_id="backfill-tsmom-12m-spy", round_id=trial_store.BACKFILL_ROUND,
            candidate_id="tsmom_timeseries", space=trial_store.DAILY_ALLOCATION,
            config={"frozen": True}, sharpe_daily=0.123, n_periods=10,
            source="docs/research/2026-06-24-candidate-strategy-survey-first-cut.md",
            date="2026-06-24",
        ),
        trial_store.TrialRecord(
            trial_id="r1-x", round_id="r1", candidate_id="x",
            space=trial_store.DAILY_ALLOCATION, config={}, sharpe_daily=0.05,
            n_periods=100, source="s", date="2026-10-01",
        ),
    ]
    trial_store.append_trials(existing, path=store)
    assert _run(store, Fetcher(_make_frames())) == 0
    records = {r.trial_id: r for r in trial_store.load_trials(store)}
    assert len(records) == 6
    for r in existing:
        assert records[r.trial_id] == r


def test_records_use_development_data_only(store, tmp_path):
    truncated = {k: v[v.index <= pd.Timestamp("2021-12-31")] for k, v in _make_frames().items()}
    store2 = tmp_path / "trials2.json"
    store2.write_text("[]\n", encoding="utf-8")
    assert _run(store, Fetcher(_make_frames(wild_after=True))) == 0
    assert _run(store2, Fetcher(truncated)) == 0
    assert store.read_bytes() == store2.read_bytes()
    records = {r.trial_id: r for r in trial_store.load_trials(store)}
    for r in records.values():
        assert r.config["dev_window"][1] <= "2021-12-31"
    assert records["backfill-gem-dual-momentum"].config["dev_window"][0] == "2012-03-01"
    assert records["backfill-tsmom-12m-spy"].config["dev_window"][0] == "2010-01-04"


def test_sharpe_helper_matches_gate_sr_hat_and_zero_variance_is_zero():
    r = np.random.default_rng(7).normal(0.0005, 0.01, 500)
    expected = deflated_sharpe_ratio(r, [0.0, 0.1])["sr_hat"]
    assert rtb._sharpe_daily(r) == pytest.approx(expected, rel=1e-12)
    assert rtb._sharpe_daily(np.full(50, 0.001)) == 0.0


def test_stored_sharpe_equals_direct_recomputation_through_the_simulator(store):
    frames = _make_frames()
    assert _run(store, Fetcher(frames)) == 0
    stored = {r.trial_id: r for r in trial_store.load_trials(store)}["backfill-gem-dual-momentum"]
    bars = etf_data.load_daily_bars(
        ["SPY", "EFA", "AGG", "BIL"], phase="development", fetch=Fetcher(frames)
    )
    idx = rcs._common_index([bars[t] for t in ["SPY", "EFA", "AGG", "BIL"]])
    sim = rcs._simulate_strategy_on_index("gem", bars, ["SPY", "EFA", "AGG"], idx)
    r = sim["equity_curve"].pct_change().iloc[1:].to_numpy(dtype=float)
    r = r[np.isfinite(r)]
    assert stored.n_periods == len(r)
    assert stored.sharpe_daily == pytest.approx(float(r.mean() / r.std(ddof=1)), rel=1e-12)


def test_fetch_error_returns_one_and_leaves_store_unchanged(store, capsys):
    def failing(ticker):
        raise RuntimeError("boom")

    before = store.read_bytes()
    assert _run(store, failing) == 1
    assert "boom" in capsys.readouterr().err
    assert store.read_bytes() == before


def test_missing_store_is_a_hard_error(tmp_path):
    missing = tmp_path / "nope.json"
    assert rtb.main(["--path", str(missing)], fetch=Fetcher(_make_frames())) == 1
    assert not missing.exists()
