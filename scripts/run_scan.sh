#!/bin/bash
cd /opt/trading-bot
source .env
/opt/trading-bot/venv/bin/python main.py scan >> /var/log/trading-bot/scan.log 2>&1
