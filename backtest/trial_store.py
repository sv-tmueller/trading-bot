"""Programme-wide trial store: every configuration the research programme has tried.

Research-only. Lives in backtest/ and is never imported by ``supabase/functions/``. No LLM, no
broker calls, no network.

Why this exists
---------------
``overfitting_gate.deflated_sharpe_ratio`` needs the Sharpe ratio of **every** configuration
tried, not just the current candidate's grid, so each extra variant raises the bar for every
later one (design spec section 5.4). This module is the single store of those Sharpe ratios. It

- rejects a duplicate ``trial_id`` (against the file and inside the incoming batch),
- enforces the per-round configuration budget (``ROUND_BUDGET``); prior trials re-run into the
  store under ``round_id == "backfill"`` are exempt from the budget but still count in
  ``programme_sharpes``,
- validates every record before anything is written, so a rejected append leaves the file
  byte-for-byte unchanged,
- writes a stable, reviewable JSON file (sorted by ``trial_id``, indent 2, sorted keys,
  trailing newline) via a same-directory temp file and ``os.replace`` (atomic).

A missing store file is a hard error (``FileNotFoundError``) and the file is never created
here: if a missing file read as ``[]``, running from the wrong directory would silently give a
short trial vector and make the DSR easier to pass. The committed ``trials.json`` (initially
``[]``) is what lets the code treat "missing" as an error. ``DEFAULT_PATH`` is relative to the
repo root, like every ``python3 -m backtest.*`` command.

The store does not compute Sharpe ratios and does not bound them: a wrongly annualized value
inflates ``sr_star`` in the gate, so the gate fails rather than passes.
"""
from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np

DAILY_ALLOCATION = "daily_allocation"
ROUND_BUDGET = 50
BACKFILL_ROUND = "backfill"
DEFAULT_PATH = Path("docs/research/pipeline/trials.json")

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class BudgetExceededError(RuntimeError):
    """Raised when appending would push a round past its configuration budget."""


@dataclass(frozen=True)
class TrialRecord:
    """One tried configuration and its Sharpe ratio.

    ``sharpe_daily`` is the **non-annualized, non-excess** daily Sharpe ratio, computed exactly
    as ``backtest.overfitting_gate`` does for ``sr_hat``::

        mean(r) / std(r, ddof=1)     # r = raw per-period (daily) returns; 0.0 if std <= 1e-12

    It is not multiplied by ``sqrt(252)`` and is not measured against cash. This is the scale
    ``overfitting_gate.deflated_sharpe_ratio`` expects for ``all_trial_sharpes``, so the value
    stored here is the same number the gate recomputes for the best trial.

    ``n_periods`` is the number of return observations behind the Sharpe (at least 2).
    ``config`` must be plain JSON (str keys; no tuples, sets, numpy scalars or NaN) so it
    round-trips unchanged. ``date`` is ``YYYY-MM-DD``.
    """

    trial_id: str
    round_id: str
    candidate_id: str
    space: str
    config: dict
    sharpe_daily: float
    n_periods: int
    source: str
    date: str


def validate_record(record: TrialRecord) -> None:
    """Raise ``ValueError`` if ``record`` would not be a well-formed store entry."""
    if not isinstance(record, TrialRecord):
        raise ValueError(f"not a TrialRecord: {record!r}")
    for name in ("trial_id", "round_id", "candidate_id", "space", "source"):
        value = getattr(record, name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string (trial {record.trial_id!r})")
    sharpe = record.sharpe_daily
    if (
        isinstance(sharpe, bool)
        or not isinstance(sharpe, (int, float))
        or not math.isfinite(sharpe)
    ):
        raise ValueError(f"sharpe_daily must be a finite number, got {sharpe!r}")
    n = record.n_periods
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise ValueError(f"n_periods must be an int >= 2, got {n!r}")
    date = record.date
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"date is not a real calendar date: {date!r}") from None
    config = record.config
    try:
        roundtrip = json.loads(json.dumps(config, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"config is not plain JSON (trial {record.trial_id!r}): {exc}") from None
    if not isinstance(config, dict) or roundtrip != config:
        raise ValueError(
            f"config does not round-trip through JSON unchanged (trial {record.trial_id!r})"
        )


def load_trials(path: Path = DEFAULT_PATH) -> List[TrialRecord]:
    """Load every stored record. A missing file raises ``FileNotFoundError``."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list of trial records")
    try:
        return [TrialRecord(**item) for item in raw]
    except TypeError as exc:
        raise ValueError(f"{path}: malformed trial record: {exc}") from None


def append_trials(
    records: Iterable[TrialRecord],
    *,
    path: Path = DEFAULT_PATH,
    round_budget: int = ROUND_BUDGET,
) -> None:
    """Validate and append ``records``; all checks run before anything is written.

    Raises ``FileNotFoundError`` (missing store), ``ValueError`` (bad record, duplicate
    ``trial_id`` in the store or the batch) or ``BudgetExceededError`` (a non-backfill round
    would exceed ``round_budget`` counting stored plus incoming records). A rejected append
    leaves the file byte-for-byte unchanged. An empty batch is a no-op and does not rewrite.
    """
    path = Path(path)
    records = list(records)  # materialize: a generator would be exhausted by validation
    existing = load_trials(path)  # also makes a missing file a hard error
    if not records:
        return

    for record in records:
        validate_record(record)

    seen = {r.trial_id for r in existing}
    for record in records:
        if record.trial_id in seen:
            raise ValueError(f"duplicate trial_id: {record.trial_id!r}")
        seen.add(record.trial_id)

    counts: Dict[str, int] = {}
    for record in existing + records:
        counts[record.round_id] = counts.get(record.round_id, 0) + 1
    for round_id in {r.round_id for r in records}:
        if round_id != BACKFILL_ROUND and counts[round_id] > round_budget:
            raise BudgetExceededError(
                f"round {round_id!r} would hold {counts[round_id]} trials, "
                f"budget is {round_budget}"
            )

    merged = sorted(existing + records, key=lambda r: r.trial_id)
    text = (
        json.dumps([asdict(r) for r in merged], indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )
    _atomic_write(path, text)


def _atomic_write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def programme_sharpes(space: str = DAILY_ALLOCATION, path: Path = DEFAULT_PATH) -> np.ndarray:
    """Return the ``sharpe_daily`` of every stored trial in ``space`` (backfill included)."""
    return np.array([r.sharpe_daily for r in load_trials(path) if r.space == space], dtype=float)
