# Weekly Trading Journal

Format and conventions for `docs/trading-journal/YYYY-Www.md` files. Each entry covers one ISO trading week and is written after the week's final candle closes (Friday US market close).

## Why these exist

The North Star for this bot is beating buy-and-hold on risk-adjusted terms — higher net gain, solid win/loss ratio, minimized drawdown — with every trading week documented. The journal is the audit trail that makes that claim verifiable: for any week, you can open the entry and read exactly what the signal was, what the bot did, how it performed, and how that compared to the benchmark. It also captures the human reasoning layer that the audit log cannot — why a config change was made mid-week, what market context surrounded a regime flip, whether a week's underperformance was expected given the signal.

A journal entry is **not**:
- A research artefact (those live in `docs/research/<topic>/`).
- A development decision (those live in `docs/decisions/`).
- A deployment runbook or incident post-mortem (those live in `docs/runbooks/`).
- A replacement for the `audit_log` table — the database row is the source of truth for what the bot did; the journal is the human-readable interpretation alongside it.

## When to write one

Write an entry for every completed ISO trading week in which the bot was live. If the bot was paused or not deployed for a full week, write a brief entry noting that and why — the gap in the record is information.

Write the entry after the Friday US market close so the full week's data is available. If `YYYY-Www.md` for the current week already exists as a draft started mid-week, complete and commit it on Friday.

## File contract

One Markdown file per ISO trading week. Use `TEMPLATE.md` as the starting point for the daily
regime bot's entries (superseded by the hourly candlestick bot as of P1, #465). Hourly-era entries
are instead rendered by `scripts/render_weekly_journal.ts` (#481) -- see
`docs/runbooks/weekly-review.md` for the invocation. Either way, an existing entry is never
overwritten silently.

## Naming and location

- Path: `docs/trading-journal/YYYY-Www.md`.
- ISO week notation: `YYYY` is the ISO year (which may differ from the calendar year for weeks spanning 31 Dec / 1 Jan), `W` is literal, `ww` is the two-digit week number zero-padded. Example: `2026-W24.md` for the week of 8–12 June 2026.
- To find the current ISO week in the shell: `date +%G-W%V`.

## Existing entries

See the files in this directory (`2026-W25.md` was the first live week; `2026-W31.md` records the
daily regime bot's deprecation). This line is intentionally not an exhaustive index — the
filesystem listing is the source of truth.
