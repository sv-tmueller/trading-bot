"""Weekly research review generator — the self-improvement loop's mechanical half.

Research-only. Never imported by ``supabase/functions/``. **No LLM, no network, no broker
calls, no third-party imports.** Reads the tested-cell ledger and renders a review for one ISO
week, including a next-round proposal derived from a documented rule rather than judgement.

Why deterministic
-----------------
The point of a weekly review is to be *comparable across weeks* and to be trustworthy without
re-reading it sceptically every time. A generator that produces the same review from the same
ledger does that; a narrative one does not. Judgement still belongs in the loop — it belongs in
the issue a human (or an agent) opens *in response* to this review, not in the accounting.

This is also why the next-round proposal is a **priority rule**, stated in
``PROPOSAL_RULE`` and applied in ``propose_next_round``, rather than a recommendation:

  1. A **PENDING** grid outranks everything — it is already frozen and pre-registered, so
     running it costs no new multiplicity and settles a question already paid for.
  2. Then a **DATA_BLOCKED** grid — same argument, and its blocker may have lifted.
  3. Then a **DIRECTIONAL_NO_GO** family — legitimately re-testable at full power.
  4. Only then an **untested** family from ``UNTESTED_CANDIDATES``.

Deliberately NOT in this file
-----------------------------
Where the review is *filed* (a doc, an issue, both) and *when* is the caller's business — see
``.github/workflows/weekly-research-review.yml``. This module only renders text, so it is
testable offline with no side effects.

Convention note: reviews live in ``docs/research/reviews/YYYY-Www.md``, **not** in
``docs/trading-journal/``. That directory's README explicitly excludes research artefacts; the
trading journal is for weeks in which the live bot traded.

Run ``python3 -m backtest.weekly_review [--as-of YYYY-MM-DD] [--out PATH]``.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

from backtest import tested_cells as tc

#: Families named as genuinely untested by prior research, in the order those docs rank them.
#: Each entry cites where the claim comes from — this list is evidence, not a wishlist.
UNTESTED_CANDIDATES: Tuple[Tuple[str, str, str], ...] = (
    (
        "vol_regime_gating", "daily",
        "#422 §'where the untested opportunity lives' — named genuinely untested, and daily/swing "
        "rather than intraday, so it clears both of that gate's walls.",
    ),
    (
        "cross_sectional_rv", "daily",
        "#422 same section — relative-value / cross-sectional signals, untested here.",
    ),
    (
        "multi_instrument_rotation", "daily",
        "#421 — the concentration concern that cannot be fixed on UPRO alone.",
    ),
    (
        "microstructure_order_flow", "intraday",
        "#422 names this as the one genuinely-intraday untested shape, and as a REVISIT TRIGGER "
        "rather than a dismissal. Needs paid data; costed before any grid is frozen.",
    ),
)

PROPOSAL_RULE = (
    "1) run a PENDING frozen grid (no new multiplicity); "
    "2) run a DATA_BLOCKED grid if its blocker lifted; "
    "3) re-test a DIRECTIONAL_NO_GO family at full power; "
    "4) freeze a new grid from the untested-candidate list."
)


def _cells(n: int) -> str:
    """``n cells`` / ``1 cell`` — the review is read by humans, so it should read like prose."""
    return f"{n} cell" if n == 1 else f"{n} cells"


def iso_week_label(as_of: date) -> str:
    """``YYYY-Www`` for ``as_of`` — the review filename and title stem."""
    year, week, _ = as_of.isocalendar()
    return f"{year}-W{week:02d}"


def programme_state() -> dict:
    """Mechanical snapshot of the research programme, straight from the ledger."""
    run = [c for c in tc.LEDGER if c.verdict not in (tc.PENDING, tc.DATA_BLOCKED)]
    pending = tc.find(verdict=tc.PENDING)
    blocked = tc.find(verdict=tc.DATA_BLOCKED)
    closed = [c for c in tc.LEDGER if c.is_closed()]
    weak = tc.find(verdict=tc.DIRECTIONAL_NO_GO)
    families = sorted({c.family for c in tc.LEDGER})
    return {
        "records": len(tc.LEDGER),
        "cells_total": sum(c.n_cells for c in tc.LEDGER),
        "cells_run": sum(c.n_cells for c in run),
        "cells_pending": sum(c.n_cells for c in pending),
        "cells_blocked": sum(c.n_cells for c in blocked),
        "closed_records": closed,
        "weak_records": list(weak),
        "pending_records": list(pending),
        "blocked_records": list(blocked),
        "families": families,
        "survivors": 0,   # no cell has ever cleared the bar in this repo; see §Survivors
    }


def propose_next_round(state: dict) -> Tuple[str, str]:
    """Apply ``PROPOSAL_RULE`` to the programme state. Returns ``(headline, rationale)``."""
    if state["pending_records"]:
        c = state["pending_records"][0]
        return (
            f"Run the frozen {c.family} / {c.cadence} / {c.vehicle} grid ({_cells(c.n_cells)})",
            f"It is already pre-registered ({c.source}), so running it consumes no NEW "
            f"multiplicity and settles a question the programme has already paid for. "
            f"Grid: {c.note}",
        )
    if state["blocked_records"]:
        c = state["blocked_records"][0]
        return (
            f"Retry the blocked {c.family} / {c.cadence} / {c.vehicle} grid",
            f"Never actually ran ({c.source}), so it is not evidence of anything — the cell is "
            f"still open. Check whether its blocker has lifted before anything new is frozen.",
        )
    if state["weak_records"]:
        c = state["weak_records"][0]
        return (
            f"Re-test {c.family} / {c.cadence} / {c.vehicle} at full power",
            f"Recorded DIRECTIONAL_NO_GO ({c.source}) — suggestive but below the promotion bar, "
            f"so a full-power re-test is legitimate rather than a duplicate.",
        )
    for family, cadence, why in UNTESTED_CANDIDATES:
        if not tc.find(family=family):
            return (
                f"Freeze a new pre-registered grid for {family} / {cadence}",
                why,
            )
    return (
        "No mechanical proposal — every candidate on record is closed or exhausted",
        "This is the point to ask whether the programme's premise needs revisiting rather than "
        "to widen further.",
    )


def render_review(as_of: Optional[date] = None) -> str:
    """Render the full weekly review markdown for the ISO week containing ``as_of``."""
    as_of = as_of or date.today()
    label = iso_week_label(as_of)
    state = programme_state()
    headline, rationale = propose_next_round(state)

    lines = [
        f"# Research review {label}",
        "",
        f"_Generated by `backtest/weekly_review.py` from the tested-cell ledger "
        f"(`backtest/tested_cells.py`) as of {as_of.isoformat()}. Deterministic: the same "
        f"ledger renders the same review._",
        "",
        "> This is a **research** review, not a trading-journal entry. "
        "`docs/trading-journal/`'s README explicitly excludes research artefacts; that "
        "directory is for weeks the live bot traded.",
        "",
        "## Programme state",
        "",
        f"- **{state['records']} records**, **{state['cells_total']} cells** on the ledger",
        f"- **{state['cells_run']} cells actually run**; "
        f"{state['cells_pending']} frozen-but-unrun; {state['cells_blocked']} blocked",
        f"- **Survivors: {state['survivors']}** — no cell has ever cleared the "
        f"after-tax-Calmar-vs-SPY bar in this repo",
        f"- Families on record: {', '.join(state['families'])}",
        "",
        "### Cumulative trials per family (run only)",
        "",
        "| family | cells run |",
        "|---|---|",
    ]
    for family in state["families"]:
        lines.append(f"| `{family}` | {tc.cumulative_trials(family)} |")

    lines += [
        "",
        "Unrun grids are excluded: a grid that never ran consumed no multiplicity, and "
        "counting it would inflate the deflated-Sharpe bar on the basis of tests that produced "
        "no numbers.",
        "",
        "## Open questions (NOT evidence — these cells are still live)",
        "",
    ]
    if state["pending_records"] or state["blocked_records"]:
        lines += ["| family | cadence | vehicle | cells | state | source |", "|---|---|---|---|---|---|"]
        for c in state["pending_records"] + state["blocked_records"]:
            lines.append(
                f"| `{c.family}` | {c.cadence} | {c.vehicle} | {c.n_cells} | "
                f"{c.verdict} | `{c.source}` |"
            )
    else:
        lines.append("None — every grid on the ledger has been run.")

    lines += [
        "",
        "## Weak results (re-testable at full power)",
        "",
    ]
    if state["weak_records"]:
        for c in state["weak_records"]:
            lines.append(
                f"- `{c.family}` / {c.cadence} / {c.vehicle} ({_cells(c.n_cells)}) — {c.note}"
            )
    else:
        lines.append("None on record.")

    lines += [
        "",
        "## Closed directions",
        "",
    ]
    for c in state["closed_records"]:
        lines.append(
            f"- `{c.family}` / {c.cadence} / {c.vehicle} — **{c.verdict}** "
            f"({_cells(c.n_cells)}) — `{c.source}`"
        )

    lines += [
        "",
        "## Proposed next round",
        "",
        f"**{headline}**",
        "",
        rationale,
        "",
        f"_Derived mechanically from the priority rule: {PROPOSAL_RULE}_",
        "",
        "## Standing reminders",
        "",
        "- A **NO-GO is a complete result.** The programme's value is in closing directions "
        "cheaply, not in finding a winner on demand.",
        "- **Widening raises the bar.** Every added round inflates cumulative multiplicity, so "
        "a late survivor needs a larger effect than an early one to be credible.",
        "- **`DATA_BLOCKED` and `PENDING` are not evidence.** Do not cite them as negatives.",
        "- Pre-registration is committed **before** results, in a strictly earlier commit.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--as-of", default=None, help="date inside the target ISO week (YYYY-MM-DD)")
    ap.add_argument("--out", default=None,
                    help="write to this path (default: print to stdout)")
    args = ap.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    text = render_review(as_of)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
