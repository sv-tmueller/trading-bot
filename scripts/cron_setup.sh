#!/bin/bash
# Add these lines to crontab: crontab -e
# All times UTC (NYSE opens 13:30 UTC during EDT, closes 20:00 UTC)

# Morning scan at 13:25 UTC (09:25 ET / 15:25 CEST) — 5 min BEFORE the open.
# Must run pre-market so signals are computed on yesterday's fully-closed daily bar.
# Running after 13:30 UTC reads an incomplete intraday bar — volume_ratio collapses to ~0.
# 25 13 * * 1-5 /opt/trading-bot/scripts/run_scan.sh

# Hourly position monitor 14:00–19:00 UTC (10:00–15:00 ET)
# 0 14-19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Pre-close check at 19:55 UTC (15:55 ET — 5 min before NYSE close)
# 55 19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

echo "Add the above cron entries with: crontab -e"
echo "Create log dir: sudo mkdir -p /var/log/trading-bot && sudo chown \$USER /var/log/trading-bot"
