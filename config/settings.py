from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

TRADING_MODE = os.getenv("TRADING_MODE", "paper")

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets"
    if TRADING_MODE == "paper"
    else "https://api.alpaca.markets"
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
MAX_PORTFOLIO_EXPOSURE = 0.20
DAILY_DRAWDOWN_LIMIT = 0.03
MAX_HOLD_DAYS = 5
RR_RATIO_MIN = 2.0

# Strategy parameters — also versioned in DB
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_LOWER = 40
RSI_UPPER = 60
VOLUME_MULTIPLIER = 1.5
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
