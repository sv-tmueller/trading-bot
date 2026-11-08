"""Offline tests for the #772 cost-model slippage recalibration study.

Research-only: the study reads one committed JSONL ledger and writes JSON/CSV under
``docs/research/``. No network, no broker, no Supabase (asserted mechanically below).

The synthetic fixtures here pin the study's own semantics; the two tests that touch the real
ledger slice it to ``date <= 2026-11-06`` and assert only frozen values (the stored
``cost_check`` reproduction and the quoted digest trigger ratios), never whole-file statistics.
"""
from __future__ import annotations

import json
import os
import re

import numpy as np
import pytest

import backtest.reflection as rfl
import backtest.run_cost_model_slippage_study as study

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_LEDGER = os.path.join(REPO_ROOT, "docs", "trading-journal", "daily-verification.jsonl")


# --------------------------------------------------------------------------- fixtures


def trade(exit_time, entry_bps=None, exit_bps=None, eoid="e1"):
    return {
        "entry_order_id": eoid,
        "entry_fill_time": exit_time,
        "exit_fill_time": exit_time,
        "entry_slippage_bps": entry_bps,
        "exit_slippage_bps": exit_bps,
    }


def row(date, trades=None, with_reflection=True):
    out = {"date": date}
    if with_reflection:
        out["reflection"] = {"engine_version": "reflection-v1", "trades": trades or []}
    return out


def ledger(rows):
    """Serialise rows into a ledger-file payload (one JSON object per line)."""
    return "".join(json.dumps(r) + "\n" for r in rows)


def write_ledger(tmp_path, rows):
    path = tmp_path / "daily-verification.jsonl"
    path.write_text(ledger(rows))
    return str(path)


def spread(n, start=0.5, step=0.25, dates=None):
    """``n`` trades with entry/exit slippage and increasing exit times (github-free)."""
    rows = []
    for i in range(n):
        d = dates[i] if dates else "2026-08-{:02d}".format(14 + i)
        t = trade(
            "2026-08-{:02d}T20:00:00+00:00".format(14 + i),
            entry_bps=-(start + step * i),
            exit_bps=(start + step * i),
            eoid="e{:03d}".format(i),
        )
        rows.append(row(d, [t]))
    return rows


# --------------------------------------------------------------------------- loading


def test_load_records_slices_to_the_freeze_end_date(tmp_path):
    path = write_ledger(
        tmp_path,
        [row("2026-10-01", [trade("2026-10-01T20:00:00+00:00", 1.0, 1.0)]),
         row("2026-12-01", [trade("2026-12-01T20:00:00+00:00", 1.0, 1.0)])],
    )

    records = study.load_records(path, end="2026-11-06")

    assert [r["date"] for r in records] == ["2026-10-01"]


def test_pooled_abs_fills_pools_both_sides_and_drops_nulls():
    trades = [
        trade("2026-08-14T20:00:00+00:00", entry_bps=-2.0, exit_bps=3.0),
        trade("2026-08-15T20:00:00+00:00", entry_bps=None, exit_bps=-0.5),
    ]

    assert sorted(study.pooled_abs_fills(trades)) == [0.5, 2.0, 3.0]


def test_side_fills_are_separated_and_absolute():
    trades = [trade("2026-08-14T20:00:00+00:00", entry_bps=-2.0, exit_bps=3.0)]

    assert study.side_fills(trades, "entry") == [2.0]
    assert study.side_fills(trades, "exit") == [3.0]


# --------------------------------------------------------------------------- windows


def test_window_assignment_uses_the_record_date_not_the_fill_time():
    records = [
        row("2026-09-30", [trade("2026-09-30T20:00:00+00:00", 1.0, 1.0)]),
        row("2026-10-01", [trade("2026-09-30T21:00:00+00:00", 2.0, 2.0)]),
    ]

    calibration = study.fills_in_window(records, study.CALIBRATION_START, study.CALIBRATION_END)
    validation = study.fills_in_window(records, study.VALIDATION_START, study.FREEZE_END)

    assert sorted(calibration) == [1.0, 1.0]
    assert sorted(validation) == [2.0, 2.0]


def test_preship_rows_without_a_reflection_key_contribute_nothing():
    records = [row("2026-08-10", with_reflection=False), row("2026-08-14", [trade("2026-08-14T20:00:00+00:00", 1.0, 1.0)])]

    assert study.pooled_abs_fills(study.all_trades(records)) == [1.0, 1.0]


# --------------------------------------------------------------------------- the fold


def test_trailing_window_fold_matches_reflection_semantics():
    records = spread(25, dates=["2026-08-{:02d}".format(1 + i) for i in range(25)])

    for i, rec in enumerate(records):
        expected_trades = rfl.build_trailing_window(records[:i], rec["reflection"]["trades"])
        expected = rfl.compute_cost_check(expected_trades)
        got = study.cost_check(study.trailing_window_trades(records, i))
        # The fold (which trades land in the window) and the pooled median are the semantics
        # under test -- those must match exactly on both sides.
        assert got["n"] == expected["n"], i
        assert got["median_abs_slippage_bps"] == expected["median_abs_slippage_bps"], i
        # The two models intentionally diverge since #779: the study is the frozen 5.0bps
        # reproducer of the 2026-11-07 verdict, the live reflection engine moved to 2.0bps.
        assert got["model_bps"] == study.MODEL_BPS == 5.0, i
        assert expected["model_bps"] == rfl.COST_MODEL_BPS == 2.0, i
        assert got["ratio"] == pytest.approx(got["median_abs_slippage_bps"] / study.MODEL_BPS), i
        assert expected["ratio"] == pytest.approx(expected["median_abs_slippage_bps"] / 2.0), i


def test_trailing_window_is_capped_at_twenty_trades():
    records = spread(25, dates=["2026-08-{:02d}".format(1 + i) for i in range(25)])

    window = study.trailing_window_trades(records, 24)

    assert len(window) == rfl.TRAILING_WINDOW
    assert window[0]["entry_order_id"] == "e005"


def test_cost_check_reproduces_a_stored_value_exactly():
    records = spread(25, dates=["2026-08-{:02d}".format(1 + i) for i in range(25)])
    for i, rec in enumerate(records):
        # Stored values are built with the STUDY's own model (5.0bps), the way the committed
        # ledger's stored cost_checks were produced. The live engine's rfl.compute_cost_check
        # would write the 2.0bps model_bps/ratio and so would no longer be a like-for-like
        # comparison -- the divergence is intentional (#779), not a reproduction failure.
        stored = study.cost_check(study.trailing_window_trades(records, i))
        assert stored["model_bps"] == 5.0
        rec["reflection"]["cost_check"] = stored

    reproduced = study.reproduce_cost_checks(records)

    assert len(reproduced) == 25
    assert all(entry["match"] for entry in reproduced)


def test_live_cost_check_diverges_from_the_frozen_study_only_in_the_model():
    # The intended #779 divergence, pinned: same window, same median and n, different model.
    records = spread(25, dates=["2026-08-{:02d}".format(1 + i) for i in range(25)])
    window = study.trailing_window_trades(records, 24)

    study_side = study.cost_check(window)
    live_side = rfl.compute_cost_check(window)

    assert study_side["n"] == live_side["n"]
    assert study_side["median_abs_slippage_bps"] == live_side["median_abs_slippage_bps"]
    assert study_side["model_bps"] == 5.0
    assert live_side["model_bps"] == 2.0
    assert live_side["ratio"] == pytest.approx(study_side["ratio"] * 2.5)


def test_reproduce_cost_checks_flags_a_mismatch():
    records = spread(25, dates=["2026-08-{:02d}".format(1 + i) for i in range(25)])
    for i, rec in enumerate(records):
        rec["reflection"]["cost_check"] = study.cost_check(study.trailing_window_trades(records, i))
    records[-1]["reflection"]["cost_check"]["median_abs_slippage_bps"] = 99.0

    reproduced = study.reproduce_cost_checks(records)

    assert [entry["date"] for entry in reproduced if not entry["match"]] == [records[-1]["date"]]


# --------------------------------------------------------------------------- bootstrap


def test_bootstrap_ci_upper_is_deterministic_under_the_frozen_seed():
    fills = [0.1, 0.2, 0.3, 0.4, 5.0, 0.5, 0.6, 0.7, 0.8, 0.9]

    first = study.bootstrap_ci_upper(fills)
    second = study.bootstrap_ci_upper(fills)

    assert first == second


def test_bootstrap_ci_upper_of_a_constant_sample_is_that_constant():
    assert study.bootstrap_ci_upper([2.0] * 20) == pytest.approx(2.0)


def test_bootstrap_ci_upper_brackets_the_sample_median():
    fills = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]

    upper = study.bootstrap_ci_upper(fills)

    assert upper >= float(np.median(fills))


# --------------------------------------------------------------------------- rolling


def test_ordered_fills_emit_entry_before_exit_within_a_trade():
    records = [
        row("2026-08-14", [trade("2026-08-14T20:00:00+00:00", -1.0, 2.0)]),
        row("2026-08-15", [trade("2026-08-15T20:00:00+00:00", -3.0, 4.0)]),
    ]

    ordered = study.ordered_fills(records)

    assert [f.value for f in ordered] == [1.0, 2.0, 3.0, 4.0]
    assert [f.is_entry for f in ordered] == [True, False, True, False]


def test_rolling_medians_qualify_only_when_the_final_fill_is_validation_dated():
    records = [
        row("2026-09-30", [trade("2026-09-30T20:00:00+00:00", -1.0, 1.0)]),
        row("2026-09-30", [trade("2026-09-30T21:00:00+00:00", -1.0, 1.0)]),
        row("2026-10-01", [trade("2026-10-01T20:00:00+00:00", -2.0, 2.0)]),
    ]

    blocks = study.rolling_window_medians(study.ordered_fills(records), window=2)
    validation = study.validation_rolling_medians(
        study.ordered_fills(records), window=2, validation_start=study.VALIDATION_START
    )

    assert len(blocks) == 5
    assert [b["end_date"] for b in validation] == ["2026-10-01", "2026-10-01"]
    assert [b["median"] for b in validation] == [pytest.approx(1.5), pytest.approx(2.0)]


def test_rolling_window_medians_report_every_contiguous_block():
    records = spread(3, dates=["2026-10-01", "2026-10-02", "2026-10-05"])

    blocks = study.rolling_window_medians(study.ordered_fills(records), window=3)

    assert len(blocks) == 4
    assert [b["end_index"] for b in blocks] == [2, 3, 4, 5]


# --------------------------------------------------------------------------- stopping rule


def test_stopping_rule_fires_when_both_clauses_hold():
    verdict = study.evaluate_stopping_rule(
        ci_upper=1.4, rolling_medians=[0.9, 1.1, 1.3]
    )

    assert verdict["fired"] is True
    assert verdict["proposed_bps"] == 2.0
    assert verdict["clause_a"]["below_model"] is True
    assert verdict["clause_b"]["all_below_model"] is True


def test_stopping_rule_does_not_fire_when_the_ci_upper_is_above_the_model():
    verdict = study.evaluate_stopping_rule(ci_upper=5.2, rolling_medians=[1.0, 1.1])

    assert verdict["fired"] is False
    assert verdict["proposed_bps"] is None


def test_stopping_rule_does_not_fire_when_one_rolling_median_reaches_the_model():
    verdict = study.evaluate_stopping_rule(ci_upper=1.4, rolling_medians=[0.9, 5.5, 1.3])

    assert verdict["fired"] is False
    assert verdict["clause_b"]["all_below_model"] is False
    assert verdict["proposed_bps"] is None


def test_stopping_rule_keeps_the_model_when_a_rolling_median_equals_it():
    verdict = study.evaluate_stopping_rule(ci_upper=1.4, rolling_medians=[0.9, 5.0])

    assert verdict["fired"] is False


def test_proposed_value_never_sits_below_the_ci_upper_bound():
    verdict = study.evaluate_stopping_rule(ci_upper=3.0, rolling_medians=[0.5])

    assert verdict["proposed_bps"] == 3.0


# --------------------------------------------------------------------------- artifacts


def test_write_artifacts_emits_a_results_json_and_a_rolling_csv(tmp_path):
    result = study.run_study(write_ledger(tmp_path, spread(25)), end="2026-11-06")

    paths = study.write_artifacts(result, str(tmp_path / "study"))

    with open(paths["results_json"]) as fh:
        written = json.load(fh)
    assert written["stopping_rule"]["model_bps"] == study.MODEL_BPS
    assert written["bootstrap"]["resamples"] == study.BOOTSTRAP_RESAMPLES
    lines = open(paths["rolling_csv"]).read().strip().splitlines()
    assert lines[0].startswith("date,n,")
    assert len(lines) == 1 + len(result["reproduction_gate"]["checks"])


# --------------------------------------------------------------------------- real ledger


def test_real_ledger_reproduces_every_stored_cost_check():
    records = study.load_records(REAL_LEDGER, end=study.FREEZE_END)

    reproduced = study.reproduce_cost_checks(records)

    assert len(reproduced) == 52
    assert [entry["date"] for entry in reproduced if not entry["match"]] == []


def test_real_ledger_reproduces_the_quoted_digest_trigger_ratios():
    records = study.load_records(REAL_LEDGER, end=study.FREEZE_END)

    reproduced = {entry["date"]: entry for entry in study.reproduce_cost_checks(records)}

    assert round(reproduced["2026-11-02"]["ratio"], 2) == 0.13
    assert round(reproduced["2026-11-03"]["ratio"], 2) == 0.13
    for day in ("2026-11-04", "2026-11-05", "2026-11-06"):
        assert round(reproduced[day]["ratio"], 2) == 0.16


def test_real_ledger_frozen_mechanical_counts():
    records = study.load_records(REAL_LEDGER, end=study.FREEZE_END)
    calibration = study.fills_in_window(records, study.CALIBRATION_START, study.CALIBRATION_END)
    validation = study.fills_in_window(records, study.VALIDATION_START, study.FREEZE_END)

    assert len(study.all_trades(records)) == 51
    assert len(calibration) == 56
    assert len(validation) == 46


# --------------------------------------------------------------------------- invariants


def test_study_module_is_python39_compatible_and_offline():
    source = open(study.__file__).read().splitlines()

    import_lines = [line for line in source if re.match(r"\s*(import|from)\s", line)]
    assert import_lines[0] == "from __future__ import annotations"
    joined = "\n".join(import_lines)
    for forbidden in ("supabase", "alpaca", "requests", "urllib", "httpx", "socket"):
        assert forbidden not in joined.lower()
