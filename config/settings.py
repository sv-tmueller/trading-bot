from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

TRADING_PAUSED: bool = os.getenv("TRADING_PAUSED", "false").lower() == "true"


def _parse_bool(raw: str) -> bool:
    """Permissive bool parser — ``1``, ``true``, ``yes`` (case-insensitive) are
    truthy; everything else (incl. empty string) is falsy. Mirrors the
    ``_is_truthy`` helper that ``daily_check.py`` previously used inline so the
    CLI/env semantics stay identical after the lift into settings.
    """
    return raw.strip().lower() in ("1", "true", "yes")


# Soak-mode for `daily_check.py`: when truthy, the script runs the full
# pipeline (regime compute, IBKR connect, audit_log writes) but skips every
# broker mutation (place_market_order, liquidate) and the matching trades
# INSERT, leaving current_state pinned. Used during the post-pivot soak week
# before flipping cron live. CLI ``--dry-run`` still wins on conflict.
DAILY_CHECK_DRY_RUN: bool = _parse_bool(os.getenv("DAILY_CHECK_DRY_RUN", "false"))

# --- IBKR connection (replaces Alpaca) ----------------------------------
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "4002"))  # 4002=paper, 4001=live
if not 1 <= IBKR_PORT <= 65535:
    raise ValueError(f"IBKR_PORT={IBKR_PORT} outside valid TCP range [1, 65535]")
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
if not 0 <= IBKR_CLIENT_ID <= 999:
    raise ValueError(f"IBKR_CLIENT_ID={IBKR_CLIENT_ID} outside safe bounds [0, 999]")

# --- Bot strategy parameters --------------------------------------------
BOT_TICKER = os.getenv("BOT_TICKER", "WSPL.DE")  # 3USL UCITS on Xetra
if not BOT_TICKER.strip():
    raise ValueError("BOT_TICKER must be a non-empty ticker symbol")
BOT_BENCHMARK = os.getenv("BOT_BENCHMARK", "SPY")  # regime-filter input
if not BOT_BENCHMARK.strip():
    raise ValueError("BOT_BENCHMARK must be a non-empty ticker symbol")

REGIME_SMA_DAYS = int(os.getenv("REGIME_SMA_DAYS", "200"))
if not 20 <= REGIME_SMA_DAYS <= 500:
    raise ValueError(f"REGIME_SMA_DAYS={REGIME_SMA_DAYS} outside safe bounds [20, 500]")

KILL_SWITCH_DRAWDOWN_PCT = float(os.getenv("KILL_SWITCH_DRAWDOWN_PCT", "0.25"))
if not 0.05 <= KILL_SWITCH_DRAWDOWN_PCT <= 0.50:
    raise ValueError(f"KILL_SWITCH_DRAWDOWN_PCT={KILL_SWITCH_DRAWDOWN_PCT} outside safe bounds [0.05, 0.50]")

KILL_SWITCH_LOOKBACK_DAYS = int(os.getenv("KILL_SWITCH_LOOKBACK_DAYS", "30"))
if not 5 <= KILL_SWITCH_LOOKBACK_DAYS <= 252:
    raise ValueError(f"KILL_SWITCH_LOOKBACK_DAYS={KILL_SWITCH_LOOKBACK_DAYS} outside safe bounds [5, 252]")


# Mechanical safety guard for agent-context broker calls (issue #168). When set,
# the four guarded `tools/ibkr_broker.py` helpers (`connect_ibkr`,
# `place_market_order`, `liquidate`, `cancel_all_orders`) raise
# `BrokerCallBlockedError` BEFORE any IBKR call. The two read-only helpers
# (`get_position`, `get_account_value`) operate on an existing `IB` instance
# and cannot be reached without first calling `connect_ibkr`, so the fail-fast
# property holds end-to-end. Production cron leaves this UNSET; pytest sets it
# via an autouse conftest fixture so any forgotten mock fails fast instead of
# reaching the live broker. We intentionally read this fresh on every call (see
# `is_claude_agent_no_broker()` below) — the perf cost is negligible and it
# means tests can flip the env var inside a test without reloading the module.
def is_claude_agent_no_broker() -> bool:
    """Return True if the agent-context broker guard (issue #168) is active.

    Reads `os.environ` fresh on every call so pytest's `monkeypatch.setenv`
    (and any test that intentionally clears it to exercise the guard-OFF path)
    is honoured without a settings reload. The four guarded `tools/ibkr_broker.py`
    helpers (`connect_ibkr`, `place_market_order`, `liquidate`,
    `cancel_all_orders`) consult this at the very top of each function.
    """
    return os.environ.get("CLAUDE_AGENT_NO_BROKER", "").lower() in ("1", "true", "yes")


# Snapshot at import time for any caller that wants the convenience. Live checks
# inside `tools/ibkr_broker.py` MUST use `is_claude_agent_no_broker()` so the
# guard remains responsive to env changes within a process.
CLAUDE_AGENT_NO_BROKER: bool = is_claude_agent_no_broker()
