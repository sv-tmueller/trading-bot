#!/bin/bash
# Add these lines to crontab: crontab -e
# All times UTC (NYSE opens 14:30 UTC, closes 21:00 UTC)

# Morning scan at 14:35 UTC (09:35 ET)
# 35 14 * * 1-5 /opt/trading-bot/scripts/run_scan.sh

# Hourly position monitor 15:00–20:00 UTC (10:00–15:00 ET)
# 0 15-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Final check at 21:00 UTC (16:00 ET)
# 0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

echo "Add the above cron entries with: crontab -e"
echo "Create log dir: sudo mkdir -p /var/log/trading-bot && sudo chown \$USER /var/log/trading-bot"
