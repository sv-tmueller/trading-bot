#!/bin/bash
cd /opt/trading-bot
source .env
/opt/trading-bot/venv/bin/python main.py monitor >> /var/log/trading-bot/monitor.log 2>&1
