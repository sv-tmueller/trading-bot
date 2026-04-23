#!/bin/bash
# Add these lines to crontab: crontab -e
# All times UTC (NYSE opens 13:30 UTC during EDT, closes 20:00 UTC)

# Morning scan at 13:35 UTC (09:35 ET / 15:35 CEST)
# 35 13 * * 1-5 /opt/trading-bot/scripts/run_scan.sh

# Hourly position monitor 14:00–20:00 UTC (10:00–16:00 ET)
# 0 14-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Final check at 21:00 UTC (17:00 ET)
# 0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

echo "Add the above cron entries with: crontab -e"
echo "Create log dir: sudo mkdir -p /var/log/trading-bot && sudo chown \$USER /var/log/trading-bot"
