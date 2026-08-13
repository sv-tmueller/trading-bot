"""Ledger of every strategy cell this repo has actually tested, and a novelty check.

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker calls, no network,
no third-party imports — the ledger is a Python literal so it is diffable, reviewable in a PR,
and needs no new dependency.

Why this exists
---------------
Establishing "has this been tested before?" was, until now, a **prose argument**. Answering it
for candlestick patterns required grepping across five separate verdict documents and reading
each one's caveats. That is slow, it is not reproducible, and it fails in the dangerous
direction: the cheapest mistake to make in a research programme with 100+ dead cells behind it
is to quietly re-test one and treat the re-run as new evidence.

This module makes the question a lookup. Every study appends its cells here; ``check_novel``
tells a future study what prior work overlaps its proposed grid, and ``is_tested`` answers the
yes/no. The ledger is the mechanism; ``docs/research/*.md`` remain the authority on *why* each
verdict was reached, and every record cites its source document.

Deliberately NOT automated
--------------------------
Records are added by hand in the same PR as the study that produced them. A scraper over the
research docs would be fragile and would silently drift; a human-written record that a reviewer
can check against the cited doc is the point. The unit tests enforce the schema, not the prose.

Verdict vocabulary
------------------
``NO_GO``            tested at adequate power, cleared nothing — the direction is closed.
``CLASS_KILL``       every cell in a whole family failed; the family does not proceed.
``DIRECTIONAL_NO_GO`` tested below the promotion bar and cleared nothing. Weaker than NO_GO:
                     suggestive, never conclusive, and re-testing at full power is legitimate.
``DATA_BLOCKED``     never actually run. **Not evidence of anything** — the cell is still open.
``PENDING``          grid frozen and pre-registered, awaiting data.

Run ``python3 -m backtest.tested_cells`` for a freshly-rendered table (no doc to go stale), or
``python3 -m backtest.tested_cells --check candlestick_pattern daily SPY`` to query overlap.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

# --- Verdict vocabulary (see module docstring) ---------------------------------------
NO_GO = "NO_GO"
CLASS_KILL = "CLASS_KILL"
DIRECTIONAL_NO_GO = "DIRECTIONAL_NO_GO"
DATA_BLOCKED = "DATA_BLOCKED"
PENDING = "PENDING"
VERDICTS = (NO_GO, CLASS_KILL, DIRECTIONAL_NO_GO, DATA_BLOCKED, PENDING)

#: Verdicts that actually close a cell. A DATA_BLOCKED or PENDING cell is still open, and a
#: DIRECTIONAL_NO_GO is explicitly re-testable at full power — conflating these with a real
#: NO_GO would let weak evidence masquerade as a settled question.
CLOSING_VERDICTS = (NO_GO, CLASS_KILL)

POWER_LEVELS = ("PROMOTABLE", "DIRECTIONAL", "UNDERPOWERED", "NONE")


@dataclass(frozen=True)
class TestedCell:
    """One tested (or pre-registered) group of cells, as recorded by the study that ran it."""

    family: str          # signal family, e.g. "candlestick_pattern", "donchian_breakout"
    cadence: str         # "daily", "hourly", "4h", "15m", "5m", "1m"
    vehicle: str         # "SPY", "ES", "GOOG", "EURUSD", "BTC", ...
    exit_style: str      # "bracket_RxRisk", "regime_flip", "eod_flat", ...
    n_cells: int         # trials in this group (feeds multiplicity accounting)
    verdict: str         # one of VERDICTS
    power: str           # one of POWER_LEVELS
    source: str          # the doc that is the authority for this record
    date: str            # YYYY-MM-DD
    note: str = ""       # one line: the load-bearing caveat, if any

    def is_closed(self) -> bool:
        """True only if this record actually settles its cells."""
        return self.verdict in CLOSING_VERDICTS


#: The ledger. Append in the same PR as the study that produced the record.
#: Every entry is checkable against its cited source document.
LEDGER: Tuple[TestedCell, ...] = (
    # --- 4h EUR/USD survey (#368 program) — CLASS KILL, 0/33 -------------------------
    TestedCell(
        family="ma_cross", cadence="4h", vehicle="EURUSD", exit_style="fixed_R",
        n_cells=15, verdict=CLASS_KILL, power="PROMOTABLE",
        source="docs/research/2026-07-15-forex-4h-survey-verdict.md", date="2026-07-15",
        note="Trend family, 15 cells. Best of all 33 reached 0.337 median after-tax Calmar vs SPY 1.309.",
    ),
    TestedCell(
        family="momentum_roc", cadence="4h", vehicle="EURUSD", exit_style="fixed_R",
        n_cells=9, verdict=CLASS_KILL, power="PROMOTABLE",
        source="docs/research/2026-07-15-forex-4h-survey-verdict.md", date="2026-07-15",
        note="Momentum family, 9 cells. Zero survivors at either co-primary preset.",
    ),
    TestedCell(
        family="mean_reversion_rsi_bollinger", cadence="4h", vehicle="EURUSD",
        exit_style="fixed_R", n_cells=9, verdict=CLASS_KILL, power="PROMOTABLE",
        source="docs/research/2026-07-15-forex-4h-survey-verdict.md", date="2026-07-15",
        note="Mean-reversion family, 9 cells. Zero survivors.",
    ),
    # --- Scalping cost wall (#309) — no edge even at ZERO cost -----------------------
    TestedCell(
        family="multi_indicator_scalp", cadence="1h", vehicle="BTC",
        exit_style="atr_stop", n_cells=1, verdict=NO_GO, power="DIRECTIONAL",
        source="docs/research/2026-06-23-scalping-cost-wall-demonstration.md",
        date="2026-06-23",
        note="-33.51% net over 301 trades; NO detectable edge before costs (gross PF 0.80).",
    ),
    TestedCell(
        family="multi_indicator_scalp", cadence="15m", vehicle="BTC",
        exit_style="atr_stop", n_cells=1, verdict=NO_GO, power="DIRECTIONAL",
        source="docs/research/2026-06-23-scalping-cost-wall-demonstration.md",
        date="2026-06-23", note="-73.83% net over 1,094 trades. More frequency, deeper loss.",
    ),
    TestedCell(
        family="multi_indicator_scalp", cadence="5m", vehicle="BTC",
        exit_style="atr_stop", n_cells=1, verdict=NO_GO, power="DIRECTIONAL",
        source="docs/research/2026-06-23-scalping-cost-wall-demonstration.md",
        date="2026-06-23", note="-97.90% net over 3,298 trades.",
    ),
    # --- Turtle / Donchian-55 bracket (#430) — NO-GO on all 12 -----------------------
    TestedCell(
        family="donchian_breakout", cadence="daily", vehicle="SPY",
        exit_style="bracket_2N_RxN", n_cells=3, verdict=NO_GO, power="PROMOTABLE",
        source="docs/research/2026-07-24-turtle-breakout-verdict.md", date="2026-07-24",
        note="R{2,3,4}. Calmar -0.071..-0.078; sits ON its random twin => no edge beyond churned beta.",
    ),
    TestedCell(
        family="donchian_breakout", cadence="daily", vehicle="ES",
        exit_style="bracket_2N_RxN", n_cells=3, verdict=NO_GO, power="PROMOTABLE",
        source="docs/research/2026-07-24-turtle-breakout-verdict.md", date="2026-07-24",
        note="R{2,3,4}. Calmar -0.057. #398 gate FAILED (DSR 0.0089).",
    ),
    TestedCell(
        family="donchian_breakout", cadence="hourly", vehicle="SPY",
        exit_style="bracket_2N_RxN", n_cells=3, verdict=DIRECTIONAL_NO_GO,
        power="DIRECTIONAL",
        source="docs/research/2026-07-24-turtle-breakout-verdict.md", date="2026-07-24",
        note="Declared non-promotable up front (yfinance 60m depth ~730d). Worse than daily.",
    ),
    TestedCell(
        family="donchian_breakout", cadence="hourly", vehicle="ES",
        exit_style="bracket_2N_RxN", n_cells=3, verdict=DIRECTIONAL_NO_GO,
        power="DIRECTIONAL",
        source="docs/research/2026-07-24-turtle-breakout-verdict.md", date="2026-07-24",
        note="Non-promotable. Calmar -0.567..-0.581.",
    ),
    # --- Opening-range breakout (#431, #434) — never actually run --------------------
    TestedCell(
        family="opening_range_breakout", cadence="5m", vehicle="SPY",
        exit_style="bracket_OR_RxRisk", n_cells=3, verdict=DATA_BLOCKED, power="NONE",
        source="docs/research/2026-07-24-orb-probe-verdict.md", date="2026-07-24",
        note="Long-only v1 probe. Alpaca key-gated; yfinance fallback reached 60 sessions (n_w=0).",
    ),
    TestedCell(
        family="opening_range_breakout", cadence="5m", vehicle="SPY",
        exit_style="bracket_OR_RxRisk", n_cells=18, verdict=PENDING, power="NONE",
        source="docs/research/2026-07-24-orb-longshort-preregistration.md", date="2026-07-24",
        note="Long/short grid: 2 dir x or_bars{1,3,6} x target{close,5R,10R}. Frozen, awaiting data.",
    ),
    # --- Candlestick patterns v1, context-free (#435) --------------------------------
    TestedCell(
        family="candlestick_pattern", cadence="daily", vehicle="GOOG",
        exit_style="bracket_patternextreme_RxRisk", n_cells=28,
        verdict=DIRECTIONAL_NO_GO, power="DIRECTIONAL",
        source="docs/research/2026-07-25-candlestick-pattern-preregistration.md",
        date="2026-07-25",
        note="0/28 clear, 3 RUINED. Harness validation only: wrong instrument, n_w=8, strong-uptrend era.",
    ),
    TestedCell(
        family="candlestick_pattern", cadence="daily", vehicle="SPY",
        exit_style="bracket_patternextreme_RxRisk", n_cells=28, verdict=NO_GO,
        power="PROMOTABLE",
        source="docs/research/2026-07-25-candlestick-pattern-preregistration.md",
        date="2026-07-26",
        note="0/28 clear, 13 RUINED; pooled #398 gate at N=84: DSR 0.0122 FAIL, PBO 0.4036 PASS, "
             "bootstrap ci_low -0.000529 FAIL.",
    ),
    # --- Candlestick patterns v2, trend context (#435) -------------------------------
    TestedCell(
        family="candlestick_pattern_context", cadence="daily", vehicle="GOOG",
        exit_style="bracket_patternextreme_RxRisk", n_cells=56,
        verdict=DIRECTIONAL_NO_GO, power="DIRECTIONAL",
        source="docs/research/2026-07-25-candlestick-context-preregistration.md",
        date="2026-07-25",
        note="0/56 clear. Context filter did NOT rescue the class; `continuation` lead is likely beta.",
    ),
    TestedCell(
        family="candlestick_pattern_context", cadence="daily", vehicle="SPY",
        exit_style="bracket_patternextreme_RxRisk", n_cells=56, verdict=NO_GO,
        power="PROMOTABLE",
        source="docs/research/2026-07-25-candlestick-context-preregistration.md",
        date="2026-07-26",
        note="0/56 clear, 4 RUINED; context did not rescue the class. Pooled #398 gate at N=84 "
             "(same run as v1): DSR 0.0122 FAIL, PBO 0.4036 PASS, bootstrap ci_low -0.000529 FAIL.",
    ),
    # --- Candlestick patterns v3, time-stop (#448 PR B) — SPY read, closed -----------------
    TestedCell(
        family="candlestick_pattern_timestop", cadence="daily", vehicle="SPY",
        exit_style="bracket_patternextreme_RxRisk_timestop", n_cells=84,
        verdict=NO_GO, power="PROMOTABLE",
        source="docs/research/2026-07-26-candlestick-timestop-preregistration.md",
        date="2026-07-26",
        note="0/84 clear (14 arms x R{2,3} x time-stop{3,5,10}, CONTEXT_NONE), 29 RUINED. "
             "Pooled #398 gate at cumulative N=168: DSR 0.0032 FAIL, PBO 0.3041 PASS, "
             "bootstrap ci_low -0.000529 FAIL -> combined FAIL. Per the pre-registration's "
             "§9 stopping rule, conditions 1 and 2 fail and condition 3 is vacuously "
             "unsatisfiable (no cell cleared the bar) -> the candlestick "
             "widening programme (v1 context-free, v2 trend-context, v3 time-stop) is "
             "closed; no round 4 (vehicle-robustness) is frozen.",
    ),
    # --- MES swing-contracts survey (#457 PR B) — SPY read, closed -------------------
    TestedCell(
        family="mes_swing", cadence="daily", vehicle="SPY",
        exit_style="bracket_2ATR_RxATR", n_cells=24, verdict=NO_GO, power="PROMOTABLE",
        source="docs/research/2026-07-26-mes-contracts-survey-preregistration.md",
        date="2026-07-27",
        note="0/24 clear at either preset (0/24 at both); closest was M1L R3 (median "
             "1.5475/1.5458 > bar but worst -0.8706/-0.8723 <= 0, fails the worst-window "
             "condition). Pooled #398 gate at cumulative N=24: DSR 0.4804 FAIL, PBO 0.1660 "
             "PASS, bootstrap ci_low -0.000465 FAIL -> combined FAIL. Per the "
             "pre-registration's §6 stopping rule, all three conditions fail (no cell "
             "clears the bar at both presets, gate fails, no cell exists to beat its "
             "twin/always-in) -> the mes_swing family is closed NO_GO; no round 2 "
             "(vol-regime gating) is frozen.",
    ),
    # --- Hourly bracket-geometry/cadence/sizing study (#566) — never actually run --------
    TestedCell(
        family="hourly_bracket_geometry_sizing", cadence="hourly", vehicle="SPY",
        exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DATA_BLOCKED, power="NONE",
        source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-data-feasibility.md",
        date="2026-08-13",
        note="R{1.0,1.5,2.0} at 60m cadence. No ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY "
             "(or TS-side ALPACA_API_KEY/ALPACA_SECRET_KEY) set and no local data/intraday "
             "drop-in present; egress to data.alpaca.markets is open (HTTP 401, not a "
             "timeout) -- key-gated, not egress-denied. yfinance fallback confirmed "
             "insufficient (#422): 60m reaches only DIRECTIONAL (n_w=2).",
    ),
    TestedCell(
        family="hourly_bracket_geometry_sizing", cadence="30m", vehicle="SPY",
        exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DATA_BLOCKED, power="NONE",
        source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-data-feasibility.md",
        date="2026-08-13",
        note="R{1.0,1.5,2.0} at 30m cadence. Same data gate as the 60m arm above; yfinance "
             "fallback measured UNDERPOWERED (60 sessions, n_w=0), confirming #422's "
             "on-record 30m depth cap and disqualifying it as a stand-in for this arm.",
    ),
    # --- Hourly bracket-geometry/cadence/sizing study (#571) -- 0/6, DIRECTIONAL_NO_GO ------
    TestedCell(
        family="hourly_bracket_geometry_sizing", cadence="hourly", vehicle="SPY",
        exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DIRECTIONAL_NO_GO,
        power="DIRECTIONAL",
        source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md",
        date="2026-08-13",
        note="R{1.0,1.5,2.0} at 60m cadence. Expectancy -0.535R..-0.538R, 0/3 clear; every "
             "cell breaches the -15% equity floor at every sizing cap {0.10,0.25,0.50,1.00}. "
             "Dominant mechanism: the frozen HOURLY_STOP_BUFFER_PCT geometry's stop distance "
             "(median $0.95-0.96) is tight enough that a single side's slippage alone (the "
             "SLIPPAGE_BPS=5bps leg, not the whole cost model) consumes ~19% of it; the full "
             "round-trip cost (plus COMMISSION_BPS=5bps) consumes more. n_w=10 < 13 -- "
             "DIRECTIONAL checkpoint input, not gate-eligible; re-testable at full power.",
    ),
    TestedCell(
        family="hourly_bracket_geometry_sizing", cadence="30m", vehicle="SPY",
        exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DIRECTIONAL_NO_GO,
        power="DIRECTIONAL",
        source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md",
        date="2026-08-13",
        note="R{1.0,1.5,2.0} at 30m cadence. Expectancy -0.739R..-0.767R, 0/3 clear -- worse "
             "than the 60m arm at every R (tighter stop distance, ~2.2x the trade count). "
             "Same mechanism as the 60m row, tighter still: a single side's slippage alone is "
             "~25% of the (shorter) stop distance here; the full round-trip cost consumes "
             "more. Same equity-floor breach. DIRECTIONAL power (n_w=10 < 13), not "
             "gate-eligible; re-testable at full power.",
    ),
)


def find(
    family: Optional[str] = None,
    cadence: Optional[str] = None,
    vehicle: Optional[str] = None,
    exit_style: Optional[str] = None,
    verdict: Optional[str] = None,
) -> Tuple[TestedCell, ...]:
    """Records matching every supplied filter. ``None`` means "any". Case-insensitive."""
    def eq(got: str, want: Optional[str]) -> bool:
        return want is None or got.lower() == want.lower()

    return tuple(
        c for c in LEDGER
        if eq(c.family, family) and eq(c.cadence, cadence) and eq(c.vehicle, vehicle)
        and eq(c.exit_style, exit_style) and eq(c.verdict, verdict)
    )


def is_tested(family: str, cadence: str, vehicle: str) -> bool:
    """True only if this (family, cadence, vehicle) has a **closing** verdict on record.

    Deliberately strict: a ``DATA_BLOCKED`` or ``PENDING`` record is not evidence, and a
    ``DIRECTIONAL_NO_GO`` is explicitly re-testable at full power. Treating any of those as
    "already tested" would let weak or absent evidence close a live question.
    """
    return any(
        c.is_closed() for c in find(family=family, cadence=cadence, vehicle=vehicle)
    )


def check_novel(family: str, cadence: str, vehicle: str) -> dict:
    """Report what prior work overlaps a proposed cell, and how strongly.

    Returns ``{"novel": bool, "closed": (...), "weak": (...), "open": (...)}`` where
    ``closed`` records would make a re-run a duplicate, ``weak`` records are directional
    reads that a full-power test may legitimately revisit, and ``open`` records are
    pre-registered-but-unrun grids that a new study would collide with.

    ``novel`` is True only when nothing at all overlaps — the honest bar for "this is new".
    """
    overlap = find(family=family, cadence=cadence, vehicle=vehicle)
    closed = tuple(c for c in overlap if c.is_closed())
    weak = tuple(c for c in overlap if c.verdict == DIRECTIONAL_NO_GO)
    open_ = tuple(c for c in overlap if c.verdict in (DATA_BLOCKED, PENDING))
    return {
        "novel": not overlap,
        "closed": closed,
        "weak": weak,
        "open": open_,
    }


def cumulative_trials(family: str) -> int:
    """Total cells ever tried in a family — the multiplicity a new round inherits.

    ``PENDING`` and ``DATA_BLOCKED`` groups are EXCLUDED: a grid that never ran consumed no
    multiplicity. Counting them would inflate the deflated-Sharpe bar on the basis of tests
    that produced no numbers.
    """
    return sum(
        c.n_cells for c in find(family=family)
        if c.verdict not in (PENDING, DATA_BLOCKED)
    )


def render_table() -> str:
    """Freshly-rendered human view. Generated on demand so no committed doc can go stale."""
    lines = [
        "Tested-cell ledger — every strategy cell this repo has run or frozen",
        f"{len(LEDGER)} records; "
        f"{sum(c.n_cells for c in LEDGER)} cells total, "
        f"{sum(c.n_cells for c in LEDGER if c.verdict not in (PENDING, DATA_BLOCKED))} actually run",
        "",
        f"{'family':<32} {'cadence':<8} {'vehicle':<8} {'n':>4} {'verdict':<18} {'power':<12}",
    ]
    for c in LEDGER:
        lines.append(
            f"{c.family:<32} {c.cadence:<8} {c.vehicle:<8} {c.n_cells:>4} "
            f"{c.verdict:<18} {c.power:<12}"
        )
    families = sorted({c.family for c in LEDGER})
    lines += ["", "cumulative trials per family (run only):"]
    for f in families:
        lines.append(f"  {f:<40} {cumulative_trials(f):>4}")
    lines += [
        "",
        "Reminder: DATA_BLOCKED and PENDING are NOT evidence — those cells are still open.",
        "DIRECTIONAL_NO_GO is suggestive only and may legitimately be re-tested at full power.",
    ]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", nargs=3, metavar=("FAMILY", "CADENCE", "VEHICLE"),
                    help="report prior work overlapping a proposed cell")
    args = ap.parse_args(argv)

    if args.check:
        family, cadence, vehicle = args.check
        res = check_novel(family, cadence, vehicle)
        print(f"proposed: family={family} cadence={cadence} vehicle={vehicle}")
        if res["novel"]:
            print("NOVEL — no prior record overlaps this cell.")
            return 0
        for label, key in (
            ("CLOSED (a re-run would be a duplicate)", "closed"),
            ("WEAK (directional only — full-power re-test is legitimate)", "weak"),
            ("OPEN (frozen or blocked, never run — a new study would collide)", "open"),
        ):
            for c in res[key]:
                print(f"  [{label}] {c.family}/{c.cadence}/{c.vehicle} "
                      f"n={c.n_cells} {c.verdict} -> {c.source}")
        return 0

    print(render_table())
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
