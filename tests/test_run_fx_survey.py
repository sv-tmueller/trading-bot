"""Tests for backtest/run_fx_survey.py -- the survey CLI (#376, #379).

Enforces the package's core discipline mechanically: without ``--smoke`` or
``--full``, ``main()`` exits BLOCKED before any data access; ``--smoke``
runs the full composition on the synthetic fixture only and never touches
the FXCM cache. ``--full`` executes the frozen survey against the REAL
FXCM cache + real SPY history -- offline-tested here via monkeypatched
``fx_survey.prepare_history``/``slice_calendar_year_windows``/``run_survey``,
so these tests never touch the cache or the network either.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest import fx_data, fx_survey, run_fx_survey


def _block_cache(monkeypatch):
    def _raise(*a, **kw):
        raise AssertionError("run_fx_survey must never touch the FXCM cache")

    monkeypatch.setattr(fx_data, "read_cache", _raise)
    monkeypatch.setattr(fx_data, "get_week_bytes", _raise)


def test_no_flag_exits_blocked_before_any_data_access(monkeypatch, capsys):
    _block_cache(monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        run_fx_survey.main([])
    assert "BLOCKED" in str(exc_info.value)
    assert "--smoke" in str(exc_info.value)


def test_smoke_runs_full_composition_with_zero_cache_access(monkeypatch, capsys):
    _block_cache(monkeypatch)
    rc = run_fx_survey.main(["--smoke"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out.upper()
    assert "33" in out  # all 33 cells always reported


def test_smoke_json_dump_is_valid_json_and_has_expected_keys(monkeypatch, tmp_path):
    _block_cache(monkeypatch)
    json_path = tmp_path / "smoke_result.json"
    rc = run_fx_survey.main(["--smoke", "--json", str(json_path)])
    assert rc == 0
    with open(json_path) as fh:
        data = json.load(fh)
    assert "survivor_results" in data
    assert len(data["survivor_results"]) == 33
    assert "family_kills" in data
    assert "class_kill" in data


def test_smoke_output_declares_synthetic_not_real_data(monkeypatch, capsys):
    """Sanity: the smoke banner must explicitly DENY being a real-data
    result (not merely omit the word "real")."""
    _block_cache(monkeypatch)
    run_fx_survey.main(["--smoke"])
    out = capsys.readouterr().out
    assert "NOT real" in out or "not real" in out.lower()
    assert "SYNTHETIC" in out.upper()


# ---------------------------------------------------------------------------
# --full (#379, stage 2c): real cache + real SPY, offline-tested via
# monkeypatched fx_survey.prepare_history/slice_calendar_year_windows/
# run_survey (never the actual cache/network).
# ---------------------------------------------------------------------------

def _stub_prep(bars_index: pd.DatetimeIndex) -> dict:
    return {
        "bars_4h": pd.DataFrame({"MidClose": [1.1] * len(bars_index)}, index=bars_index),
        "n_saturday_dropped": 7,
        "resample_report": {"n_bars": 123},
        "completeness": {2020: {"pct_missing_weeks": 0.0}},
        "history_rows": 999,
        "n_duplicates": 0,
        "adjudicated_crossings": [(2024, "missing weeks 7.55% > 2.00%")],
    }


def _stub_survey_result(measured_spread_pips: float) -> dict:
    return {
        "measured_spread_pips": measured_spread_pips,
        "windows": [{"year": 2020, "scored": True}],
        "cell_full_matrix": {}, "cell_co_primary_annual": {},
        "baseline_full_matrix": {}, "baseline_co_primary_annual": {},
        "spy_median_calmar": 1.23,
        "survivor_results": {f"cell_{i}": {"is_survivor": False} for i in range(33)},
        "family_kills": {"T": True, "M": True, "R": True},
        "class_kill": {"class_dead": True, "reason": "a_no_cell_clears_median"},
    }


def _patch_full_mode(monkeypatch, calls: dict):
    bars_index = pd.date_range("2020-01-01", periods=10, freq="4h", tz="UTC")

    def fake_prepare_history(**kwargs):
        calls["prepare_history_kwargs"] = kwargs
        return _stub_prep(bars_index)

    def fake_slice(index_4h, **kwargs):
        calls["slice_index"] = index_4h
        calls["slice_kwargs"] = kwargs
        return [{
            "year": 2020, "scored": True,
            "pre_roll_start": index_4h[0], "test_start": index_4h[0], "test_end": index_4h[-1],
        }]

    def fake_run_survey(bars_4h, windows, **kwargs):
        calls["run_survey_bars_4h"] = bars_4h
        calls["run_survey_windows"] = windows
        calls["run_survey_kwargs"] = kwargs
        return _stub_survey_result(kwargs["measured_spread_pips"])

    monkeypatch.setattr(fx_survey, "prepare_history", fake_prepare_history)
    monkeypatch.setattr(fx_survey, "slice_calendar_year_windows", fake_slice)
    monkeypatch.setattr(fx_survey, "run_survey", fake_run_survey)


def test_full_and_smoke_are_mutually_exclusive(monkeypatch):
    _block_cache(monkeypatch)
    with pytest.raises(SystemExit):
        run_fx_survey.main(["--smoke", "--full"])


def test_full_requires_spread_pips(monkeypatch):
    _block_cache(monkeypatch)
    with pytest.raises(SystemExit):
        run_fx_survey.main(["--full"])


def test_smoke_rejects_spread_pips(monkeypatch):
    _block_cache(monkeypatch)
    with pytest.raises(SystemExit):
        run_fx_survey.main(["--smoke", "--spread-pips", "0.20"])


@pytest.mark.parametrize("bad_value", ["0", "-0.5", "nan", "inf"])
def test_full_rejects_non_finite_or_non_positive_spread_pips(monkeypatch, bad_value):
    _block_cache(monkeypatch)
    with pytest.raises(SystemExit):
        run_fx_survey.main(["--full", "--spread-pips", bad_value])


def test_full_calls_prepare_history_with_fetch_false_and_frozen_whitelist(monkeypatch):
    _block_cache(monkeypatch)
    calls: dict = {}
    _patch_full_mode(monkeypatch, calls)

    rc = run_fx_survey.main(["--full", "--spread-pips", "0.20"])

    assert rc == 0
    assert calls["prepare_history_kwargs"]["fetch"] is False
    assert calls["prepare_history_kwargs"]["end_year"] == 2026
    assert (
        calls["prepare_history_kwargs"]["adjudicated_reasons"]
        == run_fx_survey.ADJUDICATED_CROSSINGS
    )
    assert calls["run_survey_kwargs"]["measured_spread_pips"] == pytest.approx(0.20)
    assert calls["run_survey_kwargs"]["spy_fetch"] is None


def test_full_end_year_is_configurable(monkeypatch):
    _block_cache(monkeypatch)
    calls: dict = {}
    _patch_full_mode(monkeypatch, calls)

    run_fx_survey.main(["--full", "--spread-pips", "0.20", "--end-year", "2024"])

    assert calls["prepare_history_kwargs"]["end_year"] == 2024


def test_full_digest_has_provenance_keys_merged_from_prepare_history(monkeypatch, tmp_path):
    _block_cache(monkeypatch)
    calls: dict = {}
    _patch_full_mode(monkeypatch, calls)
    json_path = tmp_path / "full.json"

    run_fx_survey.main(["--full", "--spread-pips", "0.20", "--json", str(json_path)])

    with open(json_path) as fh:
        data = json.load(fh)
    for key in (
        "n_saturday_dropped", "bars_4h_len", "resample_report", "completeness",
        "history_rows", "n_duplicates", "adjudicated_crossings",
    ):
        assert key in data
    assert data["n_saturday_dropped"] == 7
    assert data["bars_4h_len"] == 10
    assert len(data["survivor_results"]) == 33  # the run_survey digest is still there too


def test_full_banner_has_no_synthetic_wording(monkeypatch, capsys):
    _block_cache(monkeypatch)
    calls: dict = {}
    _patch_full_mode(monkeypatch, calls)

    run_fx_survey.main(["--full", "--spread-pips", "0.20"])

    out = capsys.readouterr().out
    assert "synthetic" not in out.lower()
    assert "real" in out.lower()
