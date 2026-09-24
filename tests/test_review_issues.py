"""Tests for backtest/review_issues.py -- deciding which stale weekly-review issues to close.

Offline, no network, no third-party imports beyond pytest. ``review_issues`` is a pure
function over a list of open issues (as ``gh issue list --json number,title`` would emit)
plus this run's own (number, label): it never calls ``gh`` itself, so it is fully testable
without a GitHub token.

Exactly one "Research review WEEK -- next-round proposal" issue should stay open at a time --
the most recent by ISO week label. Every other matching issue (an older week, a same-week
duplicate, or a backfill run for a past week while a newer week's issue is already open) is
superseded by #662's decision and should close.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backtest import review_issues as ri

REPO_ROOT = Path(__file__).resolve().parent.parent


def _issue(number: int, label: str) -> dict:
    # The em dash here is load-bearing data, not prose style: it must match the workflow's
    # literal TITLE string exactly (the em dash is deliberately kept there, see #662).
    return {"number": number, "title": f"Research review {label} — next-round proposal"}


# ---------------------------------------------------------------------------
# Title parsing
# ---------------------------------------------------------------------------

def test_parse_week_label_matches_the_exact_title():
    assert ri.parse_week_label("Research review 2026-W39 — next-round proposal") == "2026-W39"


def test_parse_week_label_rejects_a_near_miss_title():
    """A title that merely mentions a week must never be mistaken for a review issue."""
    assert ri.parse_week_label("Re: Research review 2026-W39 — next-round proposal") is None
    assert ri.parse_week_label("Research review 2026-W39 — next-round proposal (follow-up)") is None
    assert ri.parse_week_label("Research review 2026-W9 — next-round proposal") is None
    assert ri.parse_week_label("Research review 2026-W39 - next-round proposal") is None  # hyphen, not em dash


# ---------------------------------------------------------------------------
# issues_to_close -- the core decision
# ---------------------------------------------------------------------------

def test_normal_run_closes_the_single_older_issue():
    """A fresh week's issue was just created; the one older open issue supersedes and closes."""
    issues = [_issue(100, "2026-W38")]
    closed = ri.issues_to_close(issues, current_number=101, current_label="2026-W39")
    assert closed == [100]


def test_rerun_in_the_same_week_closes_nothing_new():
    """Re-running the same week finds its own issue already open -- nothing else to close."""
    issues = [_issue(101, "2026-W39")]
    closed = ri.issues_to_close(issues, current_number=101, current_label="2026-W39")
    assert closed == []


def test_current_issue_missing_from_the_open_list_is_still_kept():
    """Search lag: the just-created issue may not show up in the fetched open list yet.
    Passing it explicitly must still keep it open (never in the close list) and still close
    the genuinely older issue."""
    issues = [_issue(100, "2026-W38")]  # #101 not present yet (search lag)
    closed = ri.issues_to_close(issues, current_number=101, current_label="2026-W39")
    assert closed == [100]
    assert 101 not in closed


def test_backfill_never_closes_a_newer_week():
    """A backfill run for a past week must not close an already-open newer week's issue --
    and its own (older) issue is itself superseded and closes."""
    issues = [_issue(200, "2026-W39")]
    closed = ri.issues_to_close(issues, current_number=150, current_label="2026-W31")
    assert closed == [150]
    assert 200 not in closed


def test_same_week_duplicates_keep_only_the_highest_numbered():
    """Two issues opened for the same week (a dedup-lag double-create): keep the higher
    issue number, close the rest."""
    issues = [_issue(10, "2026-W39"), _issue(11, "2026-W39")]
    closed = ri.issues_to_close(issues, current_number=11, current_label="2026-W39")
    assert closed == [10]


def test_multiple_older_issues_all_close_keeping_only_the_latest():
    issues = [_issue(1, "2026-W10"), _issue(2, "2026-W20"), _issue(3, "2026-W30")]
    closed = ri.issues_to_close(issues, current_number=4, current_label="2026-W39")
    assert closed == [1, 2, 3]


def test_near_miss_titles_are_never_touched():
    issues = [
        {"number": 5, "title": "Fix the research review generator"},
        {"number": 6, "title": "Research review notes"},
        _issue(100, "2026-W38"),
    ]
    closed = ri.issues_to_close(issues, current_number=101, current_label="2026-W39")
    assert closed == [100]


def test_empty_open_list_with_no_current_closes_nothing():
    assert ri.issues_to_close([]) == []


def test_empty_open_list_with_a_current_closes_nothing():
    """Nothing to supersede -- the just-created issue is the only one on record."""
    assert ri.issues_to_close([], current_number=101, current_label="2026-W39") == []


def test_no_current_supplied_still_supersedes_older_duplicates_by_label():
    """Even without a current issue passed in, the newest matching issue on record is kept."""
    issues = [_issue(1, "2026-W10"), _issue(2, "2026-W20")]
    assert ri.issues_to_close(issues) == [1]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_reads_json_from_stdin_and_prints_numbers_to_close(capsys):
    payload = json.dumps([_issue(100, "2026-W38"), _issue(101, "2026-W39")])
    rc = ri.main(["--current-number", "101", "--current-label", "2026-W39"], stdin_text=payload)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == "100"


def test_cli_prints_nothing_when_there_is_nothing_to_close(capsys):
    payload = json.dumps([_issue(101, "2026-W39")])
    rc = ri.main(["--current-number", "101", "--current-label", "2026-W39"], stdin_text=payload)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_cli_works_without_current_args():
    payload = json.dumps([_issue(1, "2026-W10"), _issue(2, "2026-W20")])
    rc = ri.main([], stdin_text=payload)
    assert rc == 0


def test_cli_subprocess_reads_real_stdin():
    """End-to-end: invoke the module as a script, piping JSON on stdin, exactly as the
    workflow will."""
    payload = json.dumps([_issue(100, "2026-W38"), _issue(101, "2026-W39")])
    result = subprocess.run(
        [sys.executable, "-m", "backtest.review_issues",
         "--current-number", "101", "--current-label", "2026-W39"],
        input=payload, capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )
    assert result.stdout.strip() == "100"
