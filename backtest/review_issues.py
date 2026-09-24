"""Decide which stale weekly-research-review issues to close (#662, part 2).

Research/CI-only. Never imported by ``supabase/functions/``. No LLM, no network, no
third-party imports -- stdlib only, so it needs no dependency and cannot reach the broker or
any live trading path. The only I/O is reading a JSON array from stdin and printing issue
numbers to stdout; ``gh issue close`` itself is the caller's job (see
``.github/workflows/weekly-research-review.yml``), never this module's.

Why this exists
----------------
``.github/workflows/weekly-research-review.yml`` opens one issue per ISO week carrying the
mechanically-derived next-round proposal. Before #662 it deduped by title search and never
closed anything, so #653 (an old week's proposal) and every week before it stayed open
forever. #662's decision: exactly one "Research review WEEK -- next-round proposal" issue
should be open at a time -- the most recent by ISO week label -- and every other matching
issue (an older week, a same-week duplicate from a dedup-lag double-create, or a backfill run
for a past week while a newer week's issue is already open) is superseded and should close.

The exact title format this matches (the em dash is deliberately kept -- it is how the
workflow matches issues to past weeks, see the workflow's own header comment)::

    Research review YYYY-Www — next-round proposal

Run ``python3 -m backtest.review_issues [--current-number N] [--current-label YYYY-Www]``,
piping a JSON array of ``{"number": int, "title": str}`` objects (as ``gh issue list --json
number,title`` emits) on stdin. Prints one issue number per line to stdout -- the issues to
close -- and nothing else.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Sequence

#: Exact title format the workflow creates. A near-miss (extra text, wrong dash, unpadded
#: week, or a trailing newline) must never be mistaken for a review issue -- matched via
#: ``fullmatch`` (no ``^...$`` anchors: ``$`` alone would allow a trailing newline through).
TITLE_RE = re.compile(r"Research review (\d{4}-W\d{2}) — next-round proposal")


def parse_week_label(title: str) -> Optional[str]:
    """The ``YYYY-Www`` label if ``title`` is exactly a review-issue title, else ``None``."""
    m = TITLE_RE.fullmatch(title)
    return m.group(1) if m else None


def decide(
    issues: Sequence[dict],
    current_number: Optional[int] = None,
    current_label: Optional[str] = None,
) -> Dict[str, object]:
    """The full decision for a run: which issue to KEEP (its own number and week label), and
    which issues to close.

    ``issues`` is a sequence of ``{"number": int, "title": str}`` (as ``gh issue list --json
    number,title`` emits); titles that do not match ``TITLE_RE`` are ignored entirely -- never
    closed, never considered for "keep".

    ``current_number``/``current_label`` let the caller pass this run's own (just found-or-
    created) issue even when it is not yet present in ``issues`` -- search lag in the
    workflow's dedup lookup (#662 risk note) must not cause it to be treated as stale.

    Exactly one candidate is kept: the one with the lexicographically-greatest
    ``(week_label, issue_number)`` -- since labels are zero-padded ``YYYY-Www``, label
    comparison is chronological, and the issue-number tiebreak keeps the more recently
    created issue among same-week duplicates. Every other candidate is closed.

    Returns ``{"keep_number": int | None, "keep_label": str | None, "close": List[int]}``.
    ``keep_number``/``keep_label`` are ``None`` only when there are no candidates at all (an
    empty ``issues`` list and no current issue passed in) -- there is then nothing to keep or
    close.

    The KEPT issue is not always ``current_number``: in a backfill (an older week's run,
    created while a newer week's issue is already open), the newer open issue is kept and the
    just-created backfill issue is itself the one that closes. The caller MUST use
    ``keep_number``/``keep_label`` for its close comment/log line -- using its own
    ``current_number`` there would, in that case, tell the closed issue it superseded itself
    (#666 review finding 1).
    """
    candidates: Dict[int, str] = {}
    for issue in issues:
        label = parse_week_label(issue["title"])
        if label is not None:
            candidates[issue["number"]] = label

    if current_number is not None and current_label is not None:
        candidates.setdefault(current_number, current_label)

    if not candidates:
        return {"keep_number": None, "keep_label": None, "close": []}

    keep_number = max(candidates, key=lambda n: (candidates[n], n))
    close = sorted(n for n in candidates if n != keep_number)
    return {"keep_number": keep_number, "keep_label": candidates[keep_number], "close": close}


def issues_to_close(
    issues: Sequence[dict],
    current_number: Optional[int] = None,
    current_label: Optional[str] = None,
) -> List[int]:
    """Issue numbers to close -- the ``close`` half of :func:`decide`. Kept for callers that
    only need the close list, not which issue is kept."""
    return decide(issues, current_number=current_number, current_label=current_label)["close"]


def main(argv: Optional[List[str]] = None, stdin_text: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--current-number", type=int, default=None,
                     help="this run's own issue number, even if not yet in the open list")
    ap.add_argument("--current-label", default=None,
                     help="this run's own ISO week label (YYYY-Www)")
    args = ap.parse_args(argv)

    text = stdin_text if stdin_text is not None else sys.stdin.read()
    issues = json.loads(text) if text.strip() else []

    decision = decide(
        issues, current_number=args.current_number, current_label=args.current_label,
    )
    if decision["keep_number"] is not None:
        print(f"keep {decision['keep_number']} {decision['keep_label']}")
    for number in decision["close"]:
        print(number)
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
