"""Tests for backtest/run_fx_survey.py -- the survey CLI (#376).

Enforces the package's core discipline mechanically: without ``--smoke``,
``main()`` exits BLOCKED before any data access; ``--smoke`` runs the full
composition on the synthetic fixture only and never touches the FXCM cache.
All offline.
"""
from __future__ import annotations

import json

import pytest

from backtest import fx_data, run_fx_survey


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
