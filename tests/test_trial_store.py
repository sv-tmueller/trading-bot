"""Tests for backtest/trial_store.py -- the programme-wide trial store for DSR accounting.

Offline, no network, no third-party imports beyond numpy and pytest. Every test passes ``path=``
to a tmp file; the only read of the committed ``trials.json`` is the read-only schema test.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from backtest import trial_store as ts
from backtest.trial_store import (
    DAILY_ALLOCATION,
    DEFAULT_PATH,
    BudgetExceededError,
    TrialRecord,
    append_trials,
    load_trials,
    programme_sharpes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def rec(i, round_id="r1", space=DAILY_ALLOCATION, sharpe=0.05, **overrides):
    fields = dict(
        trial_id=f"t{i:03d}",
        round_id=round_id,
        candidate_id=f"cand-{i}",
        space=space,
        config={"lookback": i, "rule": "tsmom"},
        sharpe_daily=sharpe,
        n_periods=1000,
        source="test",
        date="2026-10-24",
    )
    fields.update(overrides)
    return TrialRecord(**fields)


@pytest.fixture
def p(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text("[]\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Plan Task 4 tests
# ---------------------------------------------------------------------------

def test_roundtrip_load_append(p):
    records = [rec(1, sharpe=0.1), rec(2, sharpe=-0.02)]
    append_trials(records, path=p)
    assert load_trials(p) == records


def test_duplicate_trial_id_rejected(p):
    append_trials([rec(1)], path=p)
    with pytest.raises(ValueError):
        append_trials([rec(1, candidate_id="other")], path=p)


def test_round_budget_enforced(p):
    append_trials([rec(i, round_id="r1") for i in range(50)], path=p)
    with pytest.raises(BudgetExceededError):
        append_trials([rec(50, round_id="r1")], path=p)


def test_backfill_round_not_budgeted(p):
    append_trials([rec(i, round_id="backfill") for i in range(60)], path=p)
    assert len(load_trials(p)) == 60


def test_programme_sharpes_filters_by_space(p):
    n_daily = 4
    records = [rec(i, sharpe=0.01 * (i + 1)) for i in range(n_daily)]
    records += [rec(10 + i, space="intraday", sharpe=9.0) for i in range(3)]
    append_trials(records, path=p)
    out = programme_sharpes(DAILY_ALLOCATION, path=p)
    assert out.shape == (n_daily,)
    assert 9.0 not in out


# ---------------------------------------------------------------------------
# Sub-plan additions
# ---------------------------------------------------------------------------

def test_duplicate_within_batch_rejected(p):
    with pytest.raises(ValueError):
        append_trials([rec(1), rec(1, candidate_id="other")], path=p)
    assert p.read_text(encoding="utf-8") == "[]\n"


def test_duplicate_against_store_leaves_file_unchanged(p):
    append_trials([rec(1)], path=p)
    before = p.read_bytes()
    with pytest.raises(ValueError):
        append_trials([rec(2), rec(1)], path=p)
    assert p.read_bytes() == before


def test_oversize_batch_rejected_and_file_unchanged(p):
    with pytest.raises(BudgetExceededError):
        append_trials([rec(i, round_id="r1") for i in range(51)], path=p)
    assert p.read_text(encoding="utf-8") == "[]\n"


def test_each_round_has_its_own_budget(p):
    append_trials([rec(i, round_id="r1") for i in range(50)], path=p)
    append_trials([rec(100 + i, round_id="r2") for i in range(50)], path=p)
    assert len(load_trials(p)) == 100


def test_round_budget_is_a_parameter(p):
    append_trials([rec(i, round_id="r1") for i in range(51)], path=p, round_budget=60)
    assert len(load_trials(p)) == 51


def test_backfill_trials_enter_programme_sharpes(p):
    append_trials([rec(i, round_id="backfill", sharpe=0.01 * i) for i in range(60)], path=p)
    assert programme_sharpes(path=p).shape == (60,)


def test_records_written_sorted_in_exact_format(p):
    append_trials([rec(3), rec(1), rec(2)], path=p)
    expected = json.dumps(
        [asdict(rec(i)) for i in (1, 2, 3)], indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    assert p.read_text(encoding="utf-8") == expected
    assert [r.trial_id for r in load_trials(p)] == ["t001", "t002", "t003"]


def test_append_merges_with_existing_in_sorted_order(p):
    append_trials([rec(5)], path=p)
    append_trials([rec(2)], path=p)
    assert [r.trial_id for r in load_trials(p)] == ["t002", "t005"]


def test_failed_replace_leaves_file_and_directory_untouched(p, monkeypatch):
    append_trials([rec(1)], path=p)
    before = p.read_bytes()

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr("backtest.trial_store.os.replace", boom)
    with pytest.raises(OSError):
        append_trials([rec(2)], path=p)
    assert p.read_bytes() == before
    assert [f.name for f in p.parent.iterdir()] == [p.name]


@pytest.mark.parametrize("bad_config", [{"a": (1, 2)}, {"a": {1, 2}}, {1: "x"}, {"a": float("nan")}])
def test_non_plain_json_config_rejected(p, bad_config):
    with pytest.raises(ValueError):
        append_trials([rec(1, config=bad_config)], path=p)
    assert p.read_text(encoding="utf-8") == "[]\n"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_sharpe_rejected(p, bad):
    with pytest.raises(ValueError):
        append_trials([rec(1, sharpe=bad)], path=p)
    assert p.read_text(encoding="utf-8") == "[]\n"


@pytest.mark.parametrize("bad", [1, 0, -5, 2.0, True])
def test_n_periods_must_be_int_at_least_two(p, bad):
    with pytest.raises(ValueError):
        append_trials([rec(1, n_periods=bad)], path=p)


def test_bad_date_rejected(p):
    with pytest.raises(ValueError):
        append_trials([rec(1, date="24/10/2026")], path=p)


def test_missing_file_is_a_hard_error(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        load_trials(missing)
    with pytest.raises(FileNotFoundError):
        append_trials([rec(1)], path=missing)
    with pytest.raises(FileNotFoundError):
        programme_sharpes(path=missing)
    assert not missing.exists()


def test_append_empty_list_does_not_rewrite(p):
    p.write_text("[\n]\n", encoding="utf-8")  # non-canonical on purpose
    append_trials([], path=p)
    assert p.read_text(encoding="utf-8") == "[\n]\n"


def test_unknown_space_returns_empty_float_array(p):
    append_trials([rec(1)], path=p)
    out = programme_sharpes("no_such_space", path=p)
    assert isinstance(out, np.ndarray)
    assert out.shape == (0,)
    assert out.dtype == float


# ---------------------------------------------------------------------------
# Committed file (read-only)
# ---------------------------------------------------------------------------

def test_committed_trials_file_is_valid():
    path = REPO_ROOT / DEFAULT_PATH
    assert path.is_file()
    records = load_trials(path)
    ids = [r.trial_id for r in records]
    assert len(ids) == len(set(ids)), "duplicate trial_id in committed trials.json"
    for r in records:
        ts.validate_record(r)
        assert math.isfinite(r.sharpe_daily)
        assert r.n_periods >= 2
