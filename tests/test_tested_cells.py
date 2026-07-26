"""Tests for backtest/tested_cells.py — the tested-cell ledger and novelty check.

Offline, no network, no third-party imports beyond pytest.

The load-bearing tests here are not the query helpers — they are the ones that stop the ledger
becoming a liability:
  - every record's cited source document must actually EXIST on disk;
  - a DATA_BLOCKED / PENDING / DIRECTIONAL_NO_GO record must never count as "already tested";
  - cumulative trial counts must exclude grids that never ran.
A ledger that misreports any of those is worse than no ledger, because it would be trusted.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backtest import tested_cells as tc

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------

def test_ledger_is_not_empty():
    assert len(tc.LEDGER) > 0


@pytest.mark.parametrize("cell", tc.LEDGER, ids=lambda c: f"{c.family}-{c.cadence}-{c.vehicle}")
def test_every_record_has_a_valid_schema(cell):
    assert cell.verdict in tc.VERDICTS, cell.verdict
    assert cell.power in tc.POWER_LEVELS, cell.power
    assert cell.n_cells > 0, "a record with zero cells records nothing"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cell.date), cell.date
    assert cell.family and cell.cadence and cell.vehicle and cell.exit_style
    assert cell.source.startswith("docs/"), cell.source


@pytest.mark.parametrize("cell", tc.LEDGER, ids=lambda c: f"{c.family}-{c.cadence}-{c.vehicle}")
def test_every_cited_source_document_exists(cell):
    """A ledger citing a document that does not exist is worse than no ledger."""
    assert (REPO_ROOT / cell.source).is_file(), f"missing source: {cell.source}"


def test_unrun_records_carry_no_power_claim():
    """A grid that never ran cannot claim statistical power."""
    for cell in tc.LEDGER:
        if cell.verdict in (tc.PENDING, tc.DATA_BLOCKED):
            assert cell.power == "NONE", (
                f"{cell.family}/{cell.vehicle} is {cell.verdict} but claims power={cell.power}"
            )


def test_closing_verdicts_are_exactly_no_go_and_class_kill():
    assert set(tc.CLOSING_VERDICTS) == {tc.NO_GO, tc.CLASS_KILL}
    # the weak/absent verdicts must NOT be closing
    for v in (tc.DIRECTIONAL_NO_GO, tc.DATA_BLOCKED, tc.PENDING):
        assert v not in tc.CLOSING_VERDICTS


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def test_find_with_no_filters_returns_everything():
    assert tc.find() == tc.LEDGER


def test_find_filters_are_case_insensitive_and_combine():
    hits = tc.find(family="DONCHIAN_BREAKOUT", cadence="Daily")
    assert len(hits) == 2                      # SPY + ES
    assert {c.vehicle for c in hits} == {"SPY", "ES"}


def test_find_by_verdict():
    for cell in tc.find(verdict=tc.PENDING):
        assert cell.verdict == tc.PENDING


def test_find_unknown_returns_empty():
    assert tc.find(family="no_such_family") == ()


# ---------------------------------------------------------------------------
# is_tested — deliberately strict
# ---------------------------------------------------------------------------

def test_is_tested_true_for_a_closed_cell():
    assert tc.is_tested("donchian_breakout", "daily", "SPY")


def test_is_tested_false_for_a_pending_cell():
    """A frozen-but-unrun grid is not evidence and must not close the question."""
    assert not tc.is_tested("opening_range_breakout", "5m", "SPY")


def test_is_tested_true_for_the_closed_candlestick_spy_cell():
    """#443: the SPY read closed both candlestick families with a real NO_GO verdict."""
    assert tc.is_tested("candlestick_pattern", "daily", "SPY")
    assert tc.is_tested("candlestick_pattern_context", "daily", "SPY")


def test_is_tested_false_for_a_data_blocked_cell():
    assert not tc.is_tested("opening_range_breakout", "5m", "SPY")


def test_is_tested_false_for_a_directional_only_cell():
    """DIRECTIONAL_NO_GO is suggestive; a full-power re-test is legitimate."""
    assert not tc.is_tested("candlestick_pattern", "daily", "GOOG")
    assert not tc.is_tested("donchian_breakout", "hourly", "SPY")


def test_is_tested_false_for_something_never_tried():
    assert not tc.is_tested("vol_regime_gating", "daily", "SPY")


# ---------------------------------------------------------------------------
# check_novel
# ---------------------------------------------------------------------------

def test_check_novel_reports_novel_only_when_nothing_overlaps():
    res = tc.check_novel("vol_regime_gating", "daily", "SPY")
    assert res["novel"] is True
    assert res["closed"] == () and res["weak"] == () and res["open"] == ()


def test_check_novel_flags_a_closed_duplicate():
    res = tc.check_novel("donchian_breakout", "daily", "SPY")
    assert res["novel"] is False
    assert len(res["closed"]) == 1
    assert res["closed"][0].verdict == tc.NO_GO


def test_check_novel_separates_weak_from_closed_from_open():
    weak = tc.check_novel("candlestick_pattern", "daily", "GOOG")
    assert weak["novel"] is False
    assert weak["weak"] and not weak["closed"]

    # #443: the SPY read closed the cell (was PENDING/open before the gate ran).
    closed = tc.check_novel("candlestick_pattern", "daily", "SPY")
    assert closed["closed"] and not closed["open"]

    open_ = tc.check_novel("opening_range_breakout", "5m", "SPY")
    assert open_["open"] and not open_["closed"]


def test_check_novel_buckets_are_disjoint():
    for family, cadence, vehicle in [
        ("donchian_breakout", "daily", "SPY"),
        ("candlestick_pattern", "daily", "GOOG"),
        ("opening_range_breakout", "5m", "SPY"),
    ]:
        res = tc.check_novel(family, cadence, vehicle)
        ids = [id(c) for bucket in ("closed", "weak", "open") for c in res[bucket]]
        assert len(ids) == len(set(ids)), "a record landed in two buckets"


# ---------------------------------------------------------------------------
# Multiplicity accounting
# ---------------------------------------------------------------------------

def test_cumulative_trials_excludes_grids_that_never_ran():
    """An unrun grid consumed no multiplicity; counting it would inflate the DSR bar."""
    # ORB has a DATA_BLOCKED(3) and a PENDING(18) record and has never run
    assert tc.cumulative_trials("opening_range_breakout") == 0
    # #443: candlestick v1 ran 28 on GOOG + 28 on SPY (the former-PENDING record, now NO_GO)
    assert tc.cumulative_trials("candlestick_pattern") == 56
    # #443: candlestick v2 ran 56 on GOOG + 56 on SPY (the former-PENDING record, now NO_GO)
    assert tc.cumulative_trials("candlestick_pattern_context") == 112
    # #448 PR B: the v3 time-stop grid ran (0/84 clear, NO_GO) — the 84 SPY trials now
    # count against future multiplicity in this family.
    assert tc.cumulative_trials("candlestick_pattern_timestop") == 84


def test_cumulative_trials_sums_multiple_run_records():
    # donchian: daily SPY 3 + daily ES 3 + hourly SPY 3 + hourly ES 3 = 12
    assert tc.cumulative_trials("donchian_breakout") == 12
    # forex class kill: 15 + 9 + 9 across three families
    assert (
        tc.cumulative_trials("ma_cross")
        + tc.cumulative_trials("momentum_roc")
        + tc.cumulative_trials("mean_reversion_rsi_bollinger")
    ) == 33


def test_cumulative_trials_of_an_unknown_family_is_zero():
    assert tc.cumulative_trials("no_such_family") == 0


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------

def test_render_table_lists_every_family_and_warns_about_weak_verdicts():
    text = tc.render_table()
    for cell in tc.LEDGER:
        assert cell.family in text
    assert "NOT evidence" in text
    assert "DIRECTIONAL_NO_GO is suggestive" in text


def test_cli_default_prints_the_table(capsys):
    assert tc.main([]) == 0
    assert "Tested-cell ledger" in capsys.readouterr().out


def test_cli_check_reports_novel(capsys):
    assert tc.main(["--check", "vol_regime_gating", "daily", "SPY"]) == 0
    assert "NOVEL" in capsys.readouterr().out


def test_cli_check_reports_a_duplicate_with_its_source(capsys):
    assert tc.main(["--check", "donchian_breakout", "daily", "SPY"]) == 0
    out = capsys.readouterr().out
    assert "CLOSED" in out
    assert "turtle-breakout-verdict" in out
