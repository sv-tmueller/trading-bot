"""Tests for backtest/weekly_review.py — the deterministic weekly research review.

Offline, no network, no LLM.

The properties worth locking are the ones that make the review trustworthy week to week:
  - it is **deterministic** (same ledger => same text), which is the whole reason it is
    generated rather than written;
  - the next-round proposal follows the documented PRIORITY RULE, in order;
  - the accounting agrees with the ledger and excludes unrun grids;
  - it never presents itself as a trading-journal entry (that README excludes research).
"""
from __future__ import annotations

from datetime import date

import pytest

from backtest import tested_cells as tc
from backtest import weekly_review as wr


# ---------------------------------------------------------------------------
# ISO week labelling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day,expected", [
    (date(2026, 7, 25), "2026-W30"),
    (date(2026, 1, 1), "2026-W01"),
    (date(2026, 12, 31), "2026-W53"),
])
def test_iso_week_label(day, expected):
    assert wr.iso_week_label(day) == expected


def test_iso_week_label_pads_single_digit_weeks():
    """Zero-padding keeps filenames sortable — W01 must not render as W1."""
    assert wr.iso_week_label(date(2026, 1, 5)) == "2026-W02"


# ---------------------------------------------------------------------------
# Programme accounting
# ---------------------------------------------------------------------------

def test_programme_state_agrees_with_the_ledger():
    st = wr.programme_state()
    assert st["records"] == len(tc.LEDGER)
    assert st["cells_total"] == sum(c.n_cells for c in tc.LEDGER)
    assert st["cells_run"] + st["cells_pending"] + st["cells_blocked"] == st["cells_total"]


def test_programme_state_excludes_unrun_grids_from_cells_run():
    st = wr.programme_state()
    unrun = sum(
        c.n_cells for c in tc.LEDGER if c.verdict in (tc.PENDING, tc.DATA_BLOCKED)
    )
    assert st["cells_run"] == st["cells_total"] - unrun


def test_survivor_count_is_zero_and_matches_the_ledger():
    """No ledger record may claim a survivor while the review reports zero."""
    st = wr.programme_state()
    assert st["survivors"] == 0
    # sanity: nothing on the ledger is recorded as a pass
    assert all(c.verdict in tc.VERDICTS for c in tc.LEDGER)
    assert not any(c.verdict == "GO" for c in tc.LEDGER)


def test_weak_and_closed_records_are_disjoint():
    st = wr.programme_state()
    weak_ids = {id(c) for c in st["weak_records"]}
    closed_ids = {id(c) for c in st["closed_records"]}
    assert weak_ids.isdisjoint(closed_ids)


# ---------------------------------------------------------------------------
# The priority rule
# ---------------------------------------------------------------------------

def _state(pending=(), blocked=(), weak=()) -> dict:
    return {
        "pending_records": list(pending),
        "blocked_records": list(blocked),
        "weak_records": list(weak),
    }


def _cell(verdict, family="fam", n=5) -> tc.TestedCell:
    return tc.TestedCell(
        family=family, cadence="daily", vehicle="SPY", exit_style="x", n_cells=n,
        verdict=verdict, power="NONE", source="docs/research/x.md", date="2026-01-01",
        note="note",
    )


def test_pending_grid_outranks_everything():
    st = _state(
        pending=[_cell(tc.PENDING)],
        blocked=[_cell(tc.DATA_BLOCKED)],
        weak=[_cell(tc.DIRECTIONAL_NO_GO)],
    )
    headline, rationale = wr.propose_next_round(st)
    assert "Run the frozen" in headline
    assert "no NEW" in rationale


def test_blocked_grid_outranks_a_weak_result():
    st = _state(blocked=[_cell(tc.DATA_BLOCKED)], weak=[_cell(tc.DIRECTIONAL_NO_GO)])
    headline, rationale = wr.propose_next_round(st)
    assert "Retry the blocked" in headline
    assert "not evidence of anything" in rationale


def test_weak_result_is_proposed_for_a_full_power_retest():
    st = _state(weak=[_cell(tc.DIRECTIONAL_NO_GO)])
    headline, rationale = wr.propose_next_round(st)
    assert "at full power" in headline
    assert "legitimate rather than a duplicate" in rationale


def test_falls_through_to_an_untested_candidate():
    headline, rationale = wr.propose_next_round(_state())
    # first untested candidate on record is the vol-regime one
    assert "vol_regime_gating" in headline
    assert "#422" in rationale


def test_untested_candidates_are_actually_absent_from_the_ledger():
    """The candidate list must not recommend something already tested."""
    for family, _cadence, _why in wr.UNTESTED_CANDIDATES:
        assert tc.find(family=family) == (), f"{family} is on the ledger already"


def test_pluralisation_reads_as_prose():
    assert wr._cells(1) == "1 cell"
    assert wr._cells(0) == "0 cells"
    assert wr._cells(28) == "28 cells"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_is_deterministic():
    """Same ledger, same date => byte-identical review. This is the point of generating it."""
    a = wr.render_review(date(2026, 7, 25))
    b = wr.render_review(date(2026, 7, 25))
    assert a == b


def test_render_includes_the_week_label_and_every_family():
    text = wr.render_review(date(2026, 7, 25))
    assert "# Research review 2026-W30" in text
    for cell in tc.LEDGER:
        assert cell.family in text


def test_render_disclaims_being_a_trading_journal_entry():
    """docs/trading-journal/'s README explicitly excludes research artefacts."""
    text = wr.render_review(date(2026, 7, 25))
    assert "not a trading-journal entry" in text


def test_render_carries_the_standing_reminders():
    text = wr.render_review(date(2026, 7, 25))
    assert "NO-GO is a complete result" in text
    assert "Widening raises the bar" in text
    assert "are not evidence" in text


def test_render_states_the_proposal_rule_it_applied():
    text = wr.render_review(date(2026, 7, 25))
    assert "Derived mechanically from the priority rule" in text
    assert "no new multiplicity" in text


def test_render_marks_open_cells_as_not_evidence():
    text = wr.render_review(date(2026, 7, 25))
    assert "NOT evidence" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_prints_to_stdout_by_default(capsys):
    assert wr.main(["--as-of", "2026-07-25"]) == 0
    assert "Research review 2026-W30" in capsys.readouterr().out


def test_cli_writes_to_out_and_creates_parent_dirs(tmp_path, capsys):
    out = tmp_path / "docs" / "research" / "reviews" / "2026-W30.md"
    assert wr.main(["--as-of", "2026-07-25", "--out", str(out)]) == 0
    assert out.is_file()
    assert "Research review 2026-W30" in out.read_text(encoding="utf-8")
    assert "wrote" in capsys.readouterr().out


def test_cli_rejects_a_malformed_date():
    with pytest.raises(ValueError):
        wr.main(["--as-of", "not-a-date"])
