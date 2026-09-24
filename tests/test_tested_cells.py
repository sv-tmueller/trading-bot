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
    """A grid that never ran (or was folded into a stronger successor) cannot claim power."""
    for cell in tc.LEDGER:
        if cell.verdict in tc.UNCOUNTED_VERDICTS:
            assert cell.power == "NONE", (
                f"{cell.family}/{cell.vehicle} is {cell.verdict} but claims power={cell.power}"
            )


def test_closing_verdicts_are_exactly_no_go_and_class_kill():
    assert set(tc.CLOSING_VERDICTS) == {tc.NO_GO, tc.CLASS_KILL}
    # the weak/absent verdicts must NOT be closing
    for v in (tc.DIRECTIONAL_NO_GO, tc.DATA_BLOCKED, tc.PENDING, tc.SUPERSEDED):
        assert v not in tc.CLOSING_VERDICTS


def test_uncounted_verdicts_are_exactly_pending_data_blocked_superseded():
    assert set(tc.UNCOUNTED_VERDICTS) == {tc.PENDING, tc.DATA_BLOCKED, tc.SUPERSEDED}


# ---------------------------------------------------------------------------
# SUPERSEDED verdict (#662)
# ---------------------------------------------------------------------------

def test_superseded_is_a_verdict_and_never_closing():
    assert tc.SUPERSEDED in tc.VERDICTS
    assert tc.SUPERSEDED not in tc.CLOSING_VERDICTS


def test_superseded_rows_apply_only_to_power_none_records():
    for cell in tc.LEDGER:
        if cell.verdict == tc.SUPERSEDED:
            assert cell.power == "NONE", (
                f"{cell.family}/{cell.vehicle} is SUPERSEDED but claims power={cell.power}"
            )


def test_non_superseded_rows_have_no_superseded_by():
    for cell in tc.LEDGER:
        if cell.verdict != tc.SUPERSEDED:
            assert cell.superseded_by == "", (
                f"{cell.family}/{cell.vehicle} is {cell.verdict} but sets superseded_by"
            )


def test_every_superseded_row_cites_a_valid_successor():
    """The successor must actually carry the evidence: same family/cadence/vehicle, a
    counted (non-UNCOUNTED) verdict, at least as many cells, and be on the ledger."""
    for cell in tc.LEDGER:
        if cell.verdict != tc.SUPERSEDED:
            continue
        assert cell.superseded_by, f"{cell.family}/{cell.vehicle} SUPERSEDED with no successor"
        successors = [
            c for c in tc.LEDGER
            if c is not cell
            and c.family == cell.family
            and c.cadence == cell.cadence
            and c.vehicle == cell.vehicle
            and c.source == cell.superseded_by
            and c.verdict not in tc.UNCOUNTED_VERDICTS
        ]
        assert successors, (
            f"{cell.family}/{cell.cadence}/{cell.vehicle}: no counted record cites "
            f"{cell.superseded_by} as its source"
        )
        assert any(s.n_cells >= cell.n_cells for s in successors), (
            f"{cell.family}/{cell.cadence}/{cell.vehicle}: successor has fewer cells than "
            f"the superseded record"
        )


def test_orb_probe_row_is_superseded_by_the_longshort_preregistration():
    rows = tc.find(
        family="opening_range_breakout", cadence="5m", vehicle="SPY", verdict=tc.SUPERSEDED,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.n_cells == 3
    assert row.power == "NONE"
    assert row.source == "docs/research/2026-07-24-orb-probe-verdict.md"
    assert row.superseded_by == "docs/research/2026-07-24-orb-longshort-preregistration.md"


def test_hourly_geometry_data_blocked_pair_is_superseded_by_the_571_verdict():
    rows = tc.find(family="hourly_bracket_geometry_sizing", vehicle="SPY", verdict=tc.SUPERSEDED)
    assert len(rows) == 2
    assert {r.cadence for r in rows} == {"hourly", "30m"}
    for row in rows:
        assert row.n_cells == 3
        assert row.power == "NONE"
        assert row.superseded_by == "docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md"


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


def test_is_tested_true_for_the_mes_swing_no_go_cell():
    """#457 PR B: the SPY read closed the frozen mes_swing grid with a real NO_GO verdict."""
    assert tc.is_tested("mes_swing", "daily", "SPY")


def test_mes_swing_row_is_on_the_ledger_as_no_go_with_24_cells():
    """#457 PR B: the SPY read flips the PENDING freeze row to a real verdict."""
    rows = tc.find(family="mes_swing", cadence="daily", vehicle="SPY")
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == tc.NO_GO
    assert row.power == "PROMOTABLE"
    assert row.n_cells == 24
    assert row.exit_style == "bracket_2ATR_RxATR"


def test_check_novel_reports_mes_swing_as_closed_once_the_no_go_row_lands():
    """A fresh family string is trivially NOVEL before its own row lands (#448-style D-C
    disclosure) — but once the SPY read closes it with NO_GO, it must show up as CLOSED, not
    OPEN (that would let a settled question look re-testable)."""
    res = tc.check_novel("mes_swing", "daily", "SPY")
    assert res["novel"] is False
    assert res["closed"] and not res["open"] and not res["weak"]


def test_is_tested_false_for_a_directional_only_cell():
    """DIRECTIONAL_NO_GO is suggestive; a full-power re-test is legitimate."""
    assert not tc.is_tested("candlestick_pattern", "daily", "GOOG")
    assert not tc.is_tested("donchian_breakout", "hourly", "SPY")


def test_is_tested_false_for_something_never_tried():
    assert not tc.is_tested("vol_regime_gating", "daily", "SPY")


def test_is_tested_false_for_the_hourly_geometry_superseded_cells():
    """#566's DATA_BLOCKED rows are now SUPERSEDED (#662) -- still not evidence on their own;
    the family is only closed if its successor (#571) is a closing verdict, which it is not
    (DIRECTIONAL_NO_GO)."""
    assert not tc.is_tested("hourly_bracket_geometry_sizing", "hourly", "SPY")
    assert not tc.is_tested("hourly_bracket_geometry_sizing", "30m", "SPY")


def test_hourly_geometry_rows_are_superseded_with_no_power_claim():
    """#662: both #566 cadence arms (60m/30m) are on the ledger as SUPERSEDED, power=NONE --
    folded into #571's DIRECTIONAL_NO_GO verdict on the same cells."""
    rows = tc.find(family="hourly_bracket_geometry_sizing", vehicle="SPY", verdict=tc.SUPERSEDED)
    assert len(rows) == 2
    assert {r.cadence for r in rows} == {"hourly", "30m"}
    for row in rows:
        assert row.verdict == tc.SUPERSEDED
        assert row.power == "NONE"
        assert row.n_cells == 3
    assert not tc.find(family="hourly_bracket_geometry_sizing", vehicle="SPY", verdict=tc.DATA_BLOCKED)


def test_hourly_geometry_directional_no_go_rows_from_571_are_recorded():
    """#571: the data-staged follow-up ran the frozen 6-cell grid and recorded its own
    DIRECTIONAL_NO_GO pair (0/6 clear), distinct from #566's DATA_BLOCKED pair on the same
    family/vehicle -- a weaker-than-NO_GO verdict since power is DIRECTIONAL, not PROMOTABLE.
    """
    rows = tc.find(
        family="hourly_bracket_geometry_sizing", vehicle="SPY", verdict=tc.DIRECTIONAL_NO_GO,
    )
    assert len(rows) == 2
    assert {r.cadence for r in rows} == {"hourly", "30m"}
    for row in rows:
        assert row.power == "DIRECTIONAL"
        assert row.n_cells == 3
        assert not row.is_closed()  # DIRECTIONAL_NO_GO never closes a family


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


def test_check_novel_separates_weak_from_closed_from_superseded():
    weak = tc.check_novel("candlestick_pattern", "daily", "GOOG")
    assert weak["novel"] is False
    assert weak["weak"] and not weak["closed"]

    # #443: the SPY read closed the cell (was PENDING/open before the gate ran).
    closed = tc.check_novel("candlestick_pattern", "daily", "SPY")
    assert closed["closed"] and not closed["open"]

    # #662: the ORB probe is now SUPERSEDED, not OPEN -- its 18-cell successor is the
    # evidence-bearing (weak) record.
    orb = tc.check_novel("opening_range_breakout", "5m", "SPY")
    assert orb["superseded"] and orb["weak"] and not orb["open"] and not orb["closed"]


def test_check_novel_reports_open_for_a_still_data_blocked_cell(monkeypatch):
    """No real ledger row is DATA_BLOCKED/PENDING any more after #662 -- exercise the "open"
    bucket against a synthetic ledger so the branch stays covered."""
    synthetic = tc.LEDGER + (
        tc.TestedCell(
            family="synthetic_open_probe", cadence="daily", vehicle="SPY", exit_style="x",
            n_cells=1, verdict=tc.DATA_BLOCKED, power="NONE",
            source="docs/research/2026-07-24-orb-probe-verdict.md", date="2026-01-01",
        ),
    )
    monkeypatch.setattr(tc, "LEDGER", synthetic)
    res = tc.check_novel("synthetic_open_probe", "daily", "SPY")
    assert res["novel"] is False
    assert res["open"] and not res["closed"] and not res["weak"] and not res["superseded"]


def test_check_novel_buckets_are_disjoint():
    for family, cadence, vehicle in [
        ("donchian_breakout", "daily", "SPY"),
        ("candlestick_pattern", "daily", "GOOG"),
        ("opening_range_breakout", "5m", "SPY"),
    ]:
        res = tc.check_novel(family, cadence, vehicle)
        ids = [
            id(c) for bucket in ("closed", "weak", "superseded", "open") for c in res[bucket]
        ]
        assert len(ids) == len(set(ids)), "a record landed in two buckets"


# ---------------------------------------------------------------------------
# Multiplicity accounting
# ---------------------------------------------------------------------------

def test_cumulative_trials_excludes_grids_that_never_ran():
    """An unrun grid consumed no multiplicity; counting it would inflate the DSR bar."""
    # #662: ORB's 3-cell probe is SUPERSEDED (excluded); its 18-cell successor actually ran
    # (#617's DIRECTIONAL_NO_GO) and is the only record that counts -- 18, not 0 and not 21
    # (no double counting the superseded probe's cells).
    assert tc.cumulative_trials("opening_range_breakout") == 18
    # #443: candlestick v1 ran 28 on GOOG + 28 on SPY (the former-PENDING record, now NO_GO)
    assert tc.cumulative_trials("candlestick_pattern") == 56
    # #443: candlestick v2 ran 56 on GOOG + 56 on SPY (the former-PENDING record, now NO_GO)
    assert tc.cumulative_trials("candlestick_pattern_context") == 112
    # #448 PR B: the v3 time-stop grid ran (0/84 clear, NO_GO) — the 84 SPY trials now
    # count against future multiplicity in this family.
    assert tc.cumulative_trials("candlestick_pattern_timestop") == 84
    # #457 PR B: the mes_swing grid ran (0/24 clear both presets, NO_GO) — the 24 SPY
    # trials now count against future multiplicity in this family.
    assert tc.cumulative_trials("mes_swing") == 24


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


def test_cumulative_trials_counts_571s_run_but_not_566s_data_blocked_rows():
    """#566's DATA_BLOCKED pair never ran -- consumed no multiplicity. #571's
    DIRECTIONAL_NO_GO pair actually ran the 6-cell grid, so it counts: 3+3=6.
    """
    assert tc.cumulative_trials("hourly_bracket_geometry_sizing") == 6


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


def test_cli_check_reports_a_superseded_record_for_the_orb_probe(capsys):
    assert tc.main(["--check", "opening_range_breakout", "5m", "SPY"]) == 0
    out = capsys.readouterr().out
    assert "SUPERSEDED" in out
    assert "orb-longshort-preregistration" in out
