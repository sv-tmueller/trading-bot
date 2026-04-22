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
from tools.database import get_daily_token_costs
from tools.notifications import (
    notify_scan_complete,
    notify_no_candidates,
    notify_no_approved,
    notify_monitor,
    notify_error,
)


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
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    # Add token cost columns to agent_logs if upgrading from an older DB
    existing = {row[1] for row in conn.execute("PRAGMA table_info(agent_logs)")}
    for col, definition in [("input_tokens", "INTEGER DEFAULT 0"), ("output_tokens", "INTEGER DEFAULT 0")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE agent_logs ADD COLUMN {col} {definition}")
    conn.commit()


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
        costs = get_daily_token_costs(conn, date.today().isoformat())
        print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
        notify_no_candidates(date.today().isoformat(), candidates.get("no_trade_reason", ""), costs["cost_usd"])
        conn.close()
        return

    print("Running Risk Review Agent...")
    risk_agent = RiskReviewAgent()
    reviewed = risk_agent.run(str(candidates), conn=conn)
    print(f"Approved: {len(reviewed.get('approved', []))} | Rejected: {len(reviewed.get('rejected', []))}")

    if not reviewed.get("approved"):
        print("No trades approved by risk review.")
        costs = get_daily_token_costs(conn, date.today().isoformat())
        print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
        notify_no_approved(date.today().isoformat(), costs["cost_usd"])
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

    costs = get_daily_token_costs(conn, date.today().isoformat())
    print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
    notify_scan_complete(
        date=date.today().isoformat(),
        market_context=market_briefing.get("market_context", "unknown"),
        candidates_found=len(candidates.get("candidates", [])),
        approved=len(reviewed.get("approved", [])),
        rejected=len(reviewed.get("rejected", [])),
        decisions=decisions.get("decisions", []),
        cost_usd=costs["cost_usd"],
    )

    conn.close()


def run_position_monitor():
    if not is_trading_day():
        return
    from datetime import datetime
    now = datetime.now().strftime("%H:%M")
    print(f"=== Position monitor — {date.today()} {now} ===")
    conn = get_db()
    actions = run_monitor(conn)
    closed = [a for a in actions if a.action == "close"]
    print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
    notify_monitor(date.today().isoformat(), now, len(actions), closed)
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
