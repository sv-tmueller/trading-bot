from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower()
if TRADING_MODE not in ("paper", "live"):
    raise ValueError(f"TRADING_MODE must be 'paper' or 'live', got: {TRADING_MODE!r}")

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets"
    if TRADING_MODE == "paper"
    else "https://api.alpaca.markets"
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

DATA_FEED = os.getenv("DATA_FEED", "iex").lower()
if DATA_FEED not in ("iex", "sip"):
    raise ValueError(f"DATA_FEED must be 'iex' or 'sip', got: {DATA_FEED!r}")

RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
if not 0.001 <= RISK_PER_TRADE <= 0.05:
    raise ValueError(f"RISK_PER_TRADE={RISK_PER_TRADE} is outside safe bounds [0.001, 0.05]")

MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
if not 1 <= MAX_POSITIONS <= 20:
    raise ValueError(f"MAX_POSITIONS={MAX_POSITIONS} is outside safe bounds [1, 20]")
MAX_PORTFOLIO_EXPOSURE = float(os.getenv("MAX_PORTFOLIO_EXPOSURE", "0.20"))
if not 0.05 <= MAX_PORTFOLIO_EXPOSURE <= 0.50:
    raise ValueError(f"MAX_PORTFOLIO_EXPOSURE={MAX_PORTFOLIO_EXPOSURE} outside safe bounds [0.05, 0.50]")

DAILY_DRAWDOWN_LIMIT = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.03"))
if not 0.005 <= DAILY_DRAWDOWN_LIMIT <= 0.20:
    raise ValueError(f"DAILY_DRAWDOWN_LIMIT={DAILY_DRAWDOWN_LIMIT} outside safe bounds [0.005, 0.20]")

MAX_HOLD_DAYS = int(os.getenv("MAX_HOLD_DAYS", "5"))
if not 1 <= MAX_HOLD_DAYS <= 30:
    raise ValueError(f"MAX_HOLD_DAYS={MAX_HOLD_DAYS} outside safe bounds [1, 30]")

RR_RATIO_MIN = float(os.getenv("RR_RATIO_MIN", "2.0"))
if not 1.0 <= RR_RATIO_MIN <= 5.0:
    raise ValueError(f"RR_RATIO_MIN={RR_RATIO_MIN} outside safe bounds [1.0, 5.0]")

# Strategy parameters — also versioned in DB
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

RSI_LOWER = float(os.getenv("RSI_LOWER", "40"))
if not 0 <= RSI_LOWER <= 50:
    raise ValueError(f"RSI_LOWER={RSI_LOWER} outside safe bounds [0, 50]")
RSI_UPPER = float(os.getenv("RSI_UPPER", "60"))
if not 50 <= RSI_UPPER <= 100:
    raise ValueError(f"RSI_UPPER={RSI_UPPER} outside safe bounds [50, 100]")
if RSI_LOWER >= RSI_UPPER:
    raise ValueError(f"RSI_LOWER ({RSI_LOWER}) must be < RSI_UPPER ({RSI_UPPER})")

VOLUME_MULTIPLIER = float(os.getenv("VOLUME_MULTIPLIER", "1.5"))
if not 0.5 <= VOLUME_MULTIPLIER <= 5.0:
    raise ValueError(f"VOLUME_MULTIPLIER={VOLUME_MULTIPLIER} outside safe bounds [0.5, 5.0]")

ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = float(os.getenv("ATR_STOP_MULTIPLIER", "1.5"))
if not 0.5 <= ATR_STOP_MULTIPLIER <= 5.0:
    raise ValueError(f"ATR_STOP_MULTIPLIER={ATR_STOP_MULTIPLIER} outside safe bounds [0.5, 5.0]")

STRICT_CROSSOVER: bool = os.getenv("STRICT_CROSSOVER", "true").lower() == "true"

TRADING_PAUSED: bool = os.getenv("TRADING_PAUSED", "false").lower() == "true"
