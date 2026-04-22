from __future__ import annotations

import sqlite3
import pandas_market_calendars as mcal
from datetime import date
from pathlib import Path

from storage.init_db import init_db, DB_PATH
from agents.market_intelligence import MarketIntelligenceAgent
from agents.strategy import StrategyAgent
from agents.risk_review import RiskReviewAgent
from agents.team_leader import TeamLeaderAgent
from monitor.position_monitor import run_monitor


def is_trading_day(today: date = None) -> bool:
    today = today or date.today()
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=today.isoformat(), end_date=today.isoformat())
    return not schedule.empty


def get_db() -> sqlite3.Connection:
    init_db(str(DB_PATH))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_morning_scan():
    if not is_trading_day():
        print("Not a trading day. Exiting.")
        return

    print(f"=== Morning scan — {date.today()} ===")
    conn = get_db()

    print("Running Market Intelligence Agent...")
    mi_agent = MarketIntelligenceAgent()
    market_briefing = mi_agent.run("Scan the watchlist and assess open positions.", conn=conn)
    print(f"Market context: {market_briefing.get('market_context')}")

    print("Running Strategy Agent...")
    strategy_agent = StrategyAgent()
    candidates = strategy_agent.run(str(market_briefing), conn=conn)
    print(f"Candidates found: {len(candidates.get('candidates', []))}")

    if not candidates.get("candidates"):
        print(f"No trade candidates: {candidates.get('no_trade_reason')}")
        conn.close()
        return

    print("Running Risk Review Agent...")
    risk_agent = RiskReviewAgent()
    reviewed = risk_agent.run(str(candidates), conn=conn)
    print(f"Approved: {len(reviewed.get('approved', []))} | Rejected: {len(reviewed.get('rejected', []))}")

    if not reviewed.get("approved"):
        print("No trades approved by risk review.")
        conn.close()
        return

    print("Running Team Leader Agent...")
    pending_stops = {t["ticker"]: t["stop_loss"] for t in reviewed["approved"]}
    pending_targets = {t["ticker"]: t["take_profit"] for t in reviewed["approved"]}
    leader_agent = TeamLeaderAgent()
    decisions = leader_agent.run(
        str(reviewed),
        conn=conn,
        pending_stops=pending_stops,
        pending_targets=pending_targets,
    )
    print(f"Session summary: {decisions.get('summary')}")

    conn.close()


def run_position_monitor():
    if not is_trading_day():
        return
    print(f"=== Position monitor — {date.today()} ===")
    conn = get_db()
    actions = run_monitor(conn)
    closed = [a for a in actions if a.action == "close"]
    print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
    conn.close()


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode == "scan":
        run_morning_scan()
    elif mode == "monitor":
        run_position_monitor()
    else:
        print(f"Unknown mode: {mode}. Use 'scan' or 'monitor'")
