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
