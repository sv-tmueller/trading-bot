# Issue #202 — Cron migration + IBKR/VPS setup doc design

**Date:** 2026-05-08
**Issue:** [#202 — ops: cron migration + IBKR/VPS setup doc (pivot Task 17) — INDEPENDENT](https://github.com/sv-tmueller/trading-bot/issues/202)
**Plan reference:** Task 17 of `docs/superpowers/plans/2026-05-07-rules-engine-pivot.md` (lines 3348-3494)
**Branch:** `feat/202-cron-ibkr-vps-doc` off `origin/spec/rules-engine-pivot` (HEAD `803a90c`)

## Context

Pivot Task 17 swaps the legacy LLM-bot cron (`scan` + `monitor`) for the new rules-engine cron (`daily_check.py` once daily + `monitor.kill_switch` hourly during market hours), and adds an operator-facing doc for installing IB Gateway + IBC + systemd on the VPS. Pure scripts and Markdown — no Python modified, no broker calls, no architectural-invariant surface touched.

Plan content for both files is fully spec'd (Task 17 §3356-3479). One judgment call deviates from the plan: the crontab-edit logic. Everything else is verbatim from the plan.

## Architecture

Two artifacts, both targeting the operator's VPS workflow:

1. **`scripts/cron_setup.sh`** — idempotent one-shot the operator runs once during cutover. Replaces the legacy 17-line stub.
2. **`docs/operations/ibkr-vps-setup.md`** — reference doc for IB Gateway install + IBC auto-login + systemd service + connectivity verification. New file.

Neither touches Python. Neither runs in CI. Neither is exercised by the pytest suite.

## Components

### `scripts/cron_setup.sh`

Approximately 35 lines. Skeleton:

```
#!/usr/bin/env bash
set -euo pipefail
# Install / update cron jobs for the rules-engine bot.
# Run as the trader user (not root): bash scripts/cron_setup.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$REPO_ROOT/venv/bin/python"

CRON_LINES=$(cat <<EOF
# BEGIN trading-bot
# Trading bot — rules-engine architecture (post-2026-05-07 pivot)
30 22 * * 1-5 cd $REPO_ROOT && $PYTHON daily_check.py >> $REPO_ROOT/logs/daily_check.log 2>&1
5 14-21 * * 1-5 cd $REPO_ROOT && $PYTHON -m monitor.kill_switch >> $REPO_ROOT/logs/kill_switch.log 2>&1
# END trading-bot
EOF
)

mkdir -p "$REPO_ROOT/logs"

EXISTING=$(crontab -l 2>/dev/null || true)
WITHOUT_BLOCK=$(echo "$EXISTING" | sed '/# BEGIN trading-bot/,/# END trading-bot/d')
WITHOUT_LEGACY=$(echo "$WITHOUT_BLOCK" | grep -vE 'main\.py (scan|monitor)|run_(scan|monitor)\.sh' || true)

(echo "$WITHOUT_LEGACY"; echo ""; echo "$CRON_LINES") | crontab -

echo "Crontab updated:"
crontab -l | grep -A4 "BEGIN trading-bot" || crontab -l
```

Deviation from plan: the crontab edit uses a `# BEGIN trading-bot` … `# END trading-bot` sentinel block instead of the plan's two `sed` invocations. Reason: the plan's first `sed` (`/# Trading bot/,/^[^#].*$/d`) deletes from the marker to the first non-comment line, which orphans the second cron line on re-run; the orphan is currently rescued only by the second `sed`'s keyword match against `kill_switch`. Renaming `kill_switch` would silently leave the orphan in the crontab. The sentinel block makes the range deletion atomic regardless of what's between the markers, and a separate `grep -v` handles the one-time legacy cleanup.

### `docs/operations/ibkr-vps-setup.md`

Approximately 80 lines, content verbatim from plan §3392-3479. Six sections:

1. Install IB Gateway — link to IB downloads, install in `/opt/ibgateway/`.
2. Configure auto-login — IBC project, `config.ini` with `IbLoginId` / `IbPassword` / `TradingMode=paper` / `ReadOnlyApi=no`.
3. Configure API in IB Gateway — port 4002 (paper) / 4001 (live), trusted IPs `127.0.0.1`, disable Read-Only API.
4. systemd service — unit at `/etc/systemd/system/ibgateway.service`, `User=trader`, `Type=simple`, `Restart=on-failure`, enable + start.
5. Verify connectivity — one-liner Python snippet using `ib_insync.IB()` to confirm `connected: True` and account list.
6. Daily reset — IB Gateway forces logout ~03:30 UTC; IBC + the systemd `Restart=on-failure` auto-recover; cron windows avoid the reset window.

## Data flow

```
Operator on VPS
  └── runs `bash scripts/cron_setup.sh` (once, during cutover)
        └── crontab -l now contains BEGIN/END trading-bot block with two cron entries
  └── follows `ibkr-vps-setup.md` (once, during cutover)
        └── IB Gateway + IBC + systemd up; connectivity one-liner returns connected=True

Cron then triggers (no further operator action)
  ├── 22:30 UTC weekdays → daily_check.py (regime check + IBKR auto-execute, issue #197)
  └── HH:05 UTC 14-21 weekdays → monitor.kill_switch (drawdown protection, issue #198)
```

## Error handling

- `set -euo pipefail` — fails on any command error, unset variable, or pipeline failure.
- `crontab -l 2>/dev/null || true` — empty-crontab is a valid starting state; no error.
- Sentinel-range delete `/# BEGIN trading-bot/,/# END trading-bot/d` — no-op when no prior block exists; idempotent on first AND repeated runs.
- `grep -vE … || true` — guards against grep returning exit 1 when nothing matches the legacy pattern.
- Plan §3486 explicitly forbids running the script in this development session (would mutate the workstation crontab). The agent honors this — only `bash -n` runs.
- The doc itself has no error path; misconfiguration is operator-visible (`ib.connect()` raises, `journalctl -u ibgateway` shows cause).

## Testing

- **Acceptance criterion 1:** `bash -n scripts/cron_setup.sh` exits 0.
- **Acceptance criterion 2:** Both cron expressions present in the script:
  - `grep -F '30 22 * * 1-5' scripts/cron_setup.sh` exits 0
  - `grep -F '5 14-21 * * 1-5' scripts/cron_setup.sh` exits 0
- **Acceptance criterion 3:** VPS doc covers all six required sections (smoke-grep for the section headers).
- **Acceptance criterion 4:** `cron_setup.sh` is NOT executed during the PR — operator-only on the VPS.
- No Python tests added or modified. The pytest suite is not gated by this PR.
- Pytest baseline note: `pytest -q` on `spec/rules-engine-pivot` HEAD currently reports 121 failures (pre-existing — old v1.14 LLM-bot test files referencing decommissioned `parameters` table from schema migration `e22de20`). These failures are scheduled for resolution by issue #200 and are orthogonal to this PR.

## Scope guardrails

Out of scope. Each is a candidate follow-up issue if needed:

- Root-vs-trader crontab migration write-up (current cron is in root's crontab; new lives in trader's).
- IBC env-var-only credentials (plan offers env-var-or-config; doc shows config.ini default).
- Log rotation policy for `$REPO_ROOT/logs/*.log` (logrotate / journald override).
- `journalctl` filter recipes beyond the one-line "check for tws_disconnected".
- Integration test that hits a real IB Gateway sandbox.
- `.gitignore` entry for `.claude/worktrees/` (skill-recommended hygiene; deferred to avoid PR churn during parallel-session window).

## Verification before commit

- `bash -n scripts/cron_setup.sh` — clean.
- `grep -F` for both cron expressions — clean.
- `wc -l` on doc — within ~80 lines.
- Section-header grep on doc — all six headers present.
- Manual eyeball comparison vs plan §3356-3494 — bash-block deviation is the documented sentinel; everything else byte-equivalent.
