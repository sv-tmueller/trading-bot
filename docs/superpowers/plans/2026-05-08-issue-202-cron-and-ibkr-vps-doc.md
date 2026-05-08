# Issue #202 — Cron migration + IBKR/VPS setup doc Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `scripts/cron_setup.sh` with the rules-engine cron entries (drop legacy `scan` / `monitor`, add `daily_check.py` and `monitor.kill_switch`) and add operator-facing `docs/operations/ibkr-vps-setup.md` covering IB Gateway + IBC auto-login + systemd setup on the VPS.

**Architecture:** Pure ops + docs change. One bash script (idempotent via BEGIN/END sentinel block) + one Markdown reference doc. No Python touched; no test suite gating; no broker calls.

**Tech Stack:** Bash (cron), Markdown.

**Spec:** `docs/superpowers/specs/2026-05-08-issue-202-cron-and-ibkr-vps-doc-design.md`
**Plan reference:** `docs/superpowers/plans/2026-05-07-rules-engine-pivot.md` §3348-3494
**Branch:** `feat/202-cron-ibkr-vps-doc` off `origin/spec/rules-engine-pivot` (HEAD `803a90c`)

---

## File structure

- Modify: `scripts/cron_setup.sh` (17-line legacy stub → ~30-line idempotent installer)
- Create: `docs/operations/ibkr-vps-setup.md` (~80 lines, six sections)

Each file has one responsibility:
- The script registers cron entries on the operator's VPS during cutover.
- The doc walks the operator through prerequisite VPS state (IB Gateway, IBC, systemd, connectivity) before the first cron fire.

Files do not import or test each other; they are linked only by operator workflow.

---

## Pytest baseline note

`pytest -q` on `spec/rules-engine-pivot` HEAD currently reports **121 pre-existing failures** (`sqlite3.OperationalError: no such table: parameters` and similar — old v1.14 LLM-bot tests referencing the decommissioned schema from migration `e22de20`). These are scheduled for resolution by issue #200. **They do not gate this PR** — this plan touches zero Python.

---

## Task 1: Replace scripts/cron_setup.sh with the rules-engine cron entries

**Files:**
- Modify: `scripts/cron_setup.sh`

**Context:** Legacy script (v1.14 LLM-bot) has commented-out `scan` + `monitor` cron entries and an `echo` install hint. Replace with idempotent installer that uses a BEGIN/END sentinel block and strips legacy entries on first run. The sentinel block is the one robustness deviation from plan §3380 (which used two sequential `sed` deletes that could orphan the second cron line on rename).

- [ ] **Step 1.1: Read the current scripts/cron_setup.sh**

Run: `cat scripts/cron_setup.sh`
Expected: 17 lines, mostly comments + commented-out `25 13 * * 1-5 ...run_scan.sh` and `0 14-19 * * 1-5 ...run_monitor.sh` and `55 19 * * 1-5 ...run_monitor.sh` lines, ending with two `echo` install hints.

- [ ] **Step 1.2: Replace the entire file with the new content**

Overwrite `scripts/cron_setup.sh` with exactly:

````bash
#!/usr/bin/env bash
set -euo pipefail
# Install / update cron jobs for the rules-engine bot.
# Run as the trader user (not root): bash scripts/cron_setup.sh
#
# Idempotent: re-running replaces the BEGIN/END trading-bot block.
# Legacy v1.14 entries (main.py scan / main.py monitor / run_*.sh) are
# stripped on first run.

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
````

- [ ] **Step 1.3: Verify syntax with `bash -n`**

Run: `bash -n scripts/cron_setup.sh`
Expected: exit code 0, no output.

- [ ] **Step 1.4: Verify both cron expressions are present**

Run: `grep -F '30 22 * * 1-5' scripts/cron_setup.sh && grep -F '5 14-21 * * 1-5' scripts/cron_setup.sh`
Expected: both lines printed; exit code 0.

- [ ] **Step 1.5: Verify legacy-stripping pattern is present**

Run: `grep -F "main\.py (scan|monitor)" scripts/cron_setup.sh`
Expected: matches the `grep -vE` line; exit code 0.

- [ ] **Step 1.6: DO NOT run the script**

The plan (§3486) explicitly forbids executing `scripts/cron_setup.sh` in this development session — it would mutate the developer workstation's crontab. Only the operator runs it on the VPS during cutover. **No `bash scripts/cron_setup.sh` invocation. Skip if tempted.**

---

## Task 2: Create docs/operations/ibkr-vps-setup.md

**Files:**
- Create: `docs/operations/ibkr-vps-setup.md`

**Context:** New operator-facing reference. Content is verbatim from the pivot plan §3392-3479 — six sections covering IB Gateway install, IBC auto-login, IB Gateway API config, systemd service, connectivity verification one-liner, daily-reset behaviour.

- [ ] **Step 2.1: Create the docs/operations directory**

Run: `mkdir -p docs/operations`
Expected: exit code 0 (directory created or already exists).

- [ ] **Step 2.2: Write docs/operations/ibkr-vps-setup.md**

Create the file with exactly:

`````markdown
# IBKR Gateway on the VPS — Setup Notes

The rules-engine bot requires IB Gateway (or TWS) running as a long-lived
process on the VPS. The bot's cron jobs (`daily_check.py`, `monitor/kill_switch.py`)
connect to it via `ib_insync` on `127.0.0.1`.

## 1. Install IB Gateway

Download from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

The "stable" build is sufficient. Install in `/opt/ibgateway/`.

## 2. Configure auto-login

Recommended: use the IBC project (https://github.com/IbcAlpha/IBC) to auto-login
non-interactively. Without IBC, you'll need to type credentials each restart.

Configure `IBC/config.ini`:
- `IbLoginId=<your-username>`
- `IbPassword=<your-password>` (or use an environment variable)
- `TradingMode=paper` (or `live`)
- `ReadOnlyApi=no`

## 3. Configure API in IB Gateway

Once running:
- File → Global Configuration → API → Settings
- Enable: "Enable ActiveX and Socket Clients"
- Set: "Socket port" = `4002` (paper) or `4001` (live)
- "Trusted IPs" → add `127.0.0.1`
- Disable: "Read-Only API" (the bot needs to place orders)

## 4. systemd service

Create `/etc/systemd/system/ibgateway.service`:

```ini
[Unit]
Description=IB Gateway (auto-login via IBC)
After=network.target

[Service]
Type=simple
User=trader
ExecStart=/opt/ibgateway/IBC/scripts/ibcstart.sh PAPER
Restart=on-failure
RestartSec=30s

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ibgateway
sudo systemctl start ibgateway
sudo systemctl status ibgateway
```

## 5. Verify connectivity

From the trader user:
```bash
cd /opt/trading-bot
venv/bin/python -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=99)
print('connected:', ib.isConnected())
print('account:', ib.managedAccounts())
ib.disconnect()
"
```

Expected: `connected: True`, account list non-empty.

## 6. Daily reset

IB Gateway forces a daily logout around 22:30 ET (~03:30 UTC). With IBC + the
systemd service above, it will auto-login again within ~30 seconds. Our cron
windows (`30 22 * * 1-5` UTC daily, `5 14-21 * * 1-5` UTC hourly) avoid this
window entirely.

If you see `tws_disconnected` notifications outside the reset window, check
`journalctl -u ibgateway -n 100` for the cause.
`````

- [ ] **Step 2.3: Verify all six section headers are present**

Run: `grep -cE '^## [1-6]\. ' docs/operations/ibkr-vps-setup.md`
Expected: `6`.

- [ ] **Step 2.4: Verify all expected port + path content is present**

Run: `grep -F '127.0.0.1' docs/operations/ibkr-vps-setup.md && grep -F '4002' docs/operations/ibkr-vps-setup.md && grep -F '/etc/systemd/system/ibgateway.service' docs/operations/ibkr-vps-setup.md && grep -F 'IBC/config.ini' docs/operations/ibkr-vps-setup.md`
Expected: each grep matches; exit code 0.

---

## Task 3: Final acceptance + commit

- [ ] **Step 3.1: Run the full acceptance bundle**

Run:
```bash
bash -n scripts/cron_setup.sh && \
  grep -F '30 22 * * 1-5' scripts/cron_setup.sh && \
  grep -F '5 14-21 * * 1-5' scripts/cron_setup.sh && \
  test "$(grep -cE '^## [1-6]\. ' docs/operations/ibkr-vps-setup.md)" = "6" && \
  echo OK
```
Expected: final line prints `OK`; exit code 0.

- [ ] **Step 3.2: Confirm no Python files changed**

Run: `git diff --name-only HEAD | grep -E '\.py$' && echo "PYTHON CHANGED" || echo "no python files changed"`
Expected: prints `no python files changed`.

- [ ] **Step 3.3: Confirm only the two expected files changed**

Run: `git status --porcelain`
Expected: exactly two lines:
```
 M scripts/cron_setup.sh
?? docs/operations/ibkr-vps-setup.md
```
(or with the `docs/superpowers/plans/...` plan file marked as `??` if this plan was added to the worktree — that's still acceptable; the spec doc was committed earlier).

- [ ] **Step 3.4: Stage and commit**

Run:
```bash
git add scripts/cron_setup.sh docs/operations/ibkr-vps-setup.md
git commit -m "$(cat <<'EOF'
ops: cron setup script + IBKR/VPS setup doc — closes #202

Replace v1.14 LLM-bot cron entries with rules-engine cron:
  30 22 * * 1-5 daily_check.py (regime + IBKR auto-execute, #197)
  5 14-21 * * 1-5 monitor.kill_switch (drawdown protection, #198)

Idempotent via BEGIN/END trading-bot sentinel block (one robustness
deviation from plan §3380 — see spec doc for rationale). Legacy
main.py scan / monitor / run_*.sh entries are stripped on first run.

Add docs/operations/ibkr-vps-setup.md (verbatim from plan §3392-3479)
covering IB Gateway install, IBC auto-login, API configuration, systemd
service, connectivity verification, and daily-reset behaviour.

Pure ops + docs change — no Python modified, no broker calls, pytest
suite unchanged. Pre-existing 121 failures on spec/rules-engine-pivot
(scheduled for resolution by #200) are orthogonal to this PR.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```
Expected: commit lands on `feat/202-cron-ibkr-vps-doc`.

- [ ] **Step 3.5: Verify commit landed**

Run: `git log --oneline -1`
Expected: top line is the new "ops: cron setup script..." commit.

---

## Final acceptance summary

- [ ] Task 1 complete: `scripts/cron_setup.sh` rewritten with sentinel block; `bash -n` passes; both cron expressions present.
- [ ] Task 2 complete: `docs/operations/ibkr-vps-setup.md` created; six section headers present; port + path content checks pass.
- [ ] Task 3 complete: full acceptance bundle prints `OK`; no Python files changed; commit lands on the feature branch with conventional-commit message and `closes #202`.
- [ ] Engineer did NOT execute `scripts/cron_setup.sh` (would mutate developer workstation crontab).
