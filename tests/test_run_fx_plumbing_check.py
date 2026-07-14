"""Tests for backtest/run_fx_plumbing_check.py's pure threshold-evaluation
helper (reviewer round-1 must-fix 3: the crossed-quotes threshold must be
wired mechanically into ``blocked_reasons``, not adjudicated by narrative
alone; extracted into a pure, unit-tested helper per the reviewer's
recommendation).

No network, no file I/O — every case below calls ``evaluate_blocked_reasons``
directly with hand-built completeness/rate inputs.
"""
from __future__ import annotations

import backtest.run_fx_plumbing_check as runner


def _completeness(**years) -> dict:
    """Build a minimal completeness_report()-shaped dict: each kwarg is
    ``year=(pct_missing_weeks, pct_rows_missing)``."""
    return {
        year: {"pct_missing_weeks": pmw, "pct_rows_missing": prm}
        for year, (pmw, prm) in years.items()
    }


def test_no_reasons_when_everything_under_threshold():
    completeness = _completeness(**{"2023": (0.0, 0.0)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2023"],
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=0,
    )
    assert reasons == []


def test_missing_weeks_over_threshold_fires():
    completeness = _completeness(**{"2024": (0.03, 0.0)})  # 3% > 2% default
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2024"],
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=0,
    )
    assert len(reasons) == 1
    assert reasons[0][0] == "2024"
    assert "missing weeks" in reasons[0][1]


def test_missing_rows_over_threshold_fires():
    completeness = _completeness(**{"2024": (0.0, 0.06)})  # 6% > 5% default
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2024"],
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=0,
    )
    assert len(reasons) == 1
    assert "missing rows" in reasons[0][1]


def test_incomplete_current_year_is_excluded_from_threshold_check():
    """A year NOT in complete_years (e.g. the current, still-publishing
    year) must never contribute a blocked reason, however bad its numbers."""
    completeness = _completeness(**{"2026": (0.9, 0.9)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=[],  # 2026 excluded
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=0,
    )
    assert reasons == []


def test_coherence_rate_over_threshold_fires():
    completeness = _completeness(**{"2023": (0.0, 0.0)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2023"],
        pct_coherence=0.002, pct_crossed_quotes=0.0, n_saturday_bars=0,  # 0.2% > 0.1%
    )
    assert len(reasons) == 1
    assert "coherence" in reasons[0][1]


def test_crossed_quotes_rate_over_threshold_fires_mechanically():
    """The must-fix: crossed-quotes crossing the same 0.1% threshold family
    as coherence must reach blocked_reasons on its own, not only via
    narrative adjudication in the research note."""
    completeness = _completeness(**{"2023": (0.0, 0.0)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2023"],
        pct_coherence=0.0, pct_crossed_quotes=0.0238, n_saturday_bars=0,  # 2.38% > 0.1%
    )
    assert len(reasons) == 1
    assert "crossed-quotes" in reasons[0][1]


def test_saturday_bars_found_fires_mechanically():
    """The mechanical check that would have caught reviewer round-1
    must-fix 1: ANY Saturday-UTC bar is a hard BLOCKED signal."""
    completeness = _completeness(**{"2023": (0.0, 0.0)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2023"],
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=5,
    )
    assert len(reasons) == 1
    assert "Saturday" in reasons[0][1]


def test_multiple_reasons_all_reported_not_short_circuited():
    completeness = _completeness(**{"2024": (0.03, 0.06)})
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2024"],
        pct_coherence=0.002, pct_crossed_quotes=0.0238, n_saturday_bars=1,
    )
    # 2 completeness reasons + coherence + crossed-quotes + saturday = 5
    assert len(reasons) == 5


def test_custom_thresholds_are_honored():
    completeness = _completeness(**{"2023": (0.03, 0.0)})
    # With a looser custom threshold, 3% missing weeks no longer fires.
    reasons = runner.evaluate_blocked_reasons(
        completeness, complete_years=["2023"],
        pct_coherence=0.0, pct_crossed_quotes=0.0, n_saturday_bars=0,
        max_pct_missing_weeks=0.05,
    )
    assert reasons == []
