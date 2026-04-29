from __future__ import annotations

import json
import sqlite3
import traceback
import pandas_market_calendars as mcal
from datetime import date
from pathlib import Path

from config import settings
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
    notify_paused,
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
    # Add trailing_high column to trades for trailing-stop support (issue #67)
    trade_cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    if "trailing_high" not in trade_cols:
        conn.execute("ALTER TABLE trades ADD COLUMN trailing_high REAL")
    conn.commit()


def _scan_already_ran(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM agent_logs WHERE agent_name = 'team_leader' AND cycle_date = ?",
        (date.today().isoformat(),),
    ).fetchone()
    return row is not None


def _reconcile_positions(conn: sqlite3.Connection) -> None:
    from tools.broker import get_alpaca_positions
    from tools.database import get_open_trades

    alpaca_positions = get_alpaca_positions()
    db_trades = get_open_trades(conn)

    alpaca_tickers = {p["ticker"] for p in alpaca_positions}
    db_tickers = {t["ticker"] for t in db_trades}

    ghost_tickers = sorted(alpaca_tickers - db_tickers)
    phantom_tickers = sorted(db_tickers - alpaca_tickers)

    if ghost_tickers or phantom_tickers:
        parts = []
        if ghost_tickers:
            parts.append(f"ghost positions (Alpaca has but DB missing): {ghost_tickers}")
        if phantom_tickers:
            parts.append(f"phantom DB entries (DB open but Alpaca closed): {phantom_tickers}")
        message = "Position reconciliation mismatch — " + "; ".join(parts)
        notify_error("reconciliation", message)


def run_morning_scan(dry_run: bool = False):
    if not is_trading_day():
        print("Not a trading day. Exiting.")
        return

    if settings.TRADING_PAUSED:
        print("Trading paused — skipping scan (TRADING_PAUSED=true).")
        notify_paused(date.today().isoformat())
        return

    conn = None
    try:
        print(f"=== Morning scan — {date.today()} ===")
        conn = get_db()

        if _scan_already_ran(conn):
            print("Morning scan already completed today. Skipping.")
            return

        try:
            _reconcile_positions(conn)
        except Exception as e:
            notify_error("reconciliation", f"Reconciliation check failed: {e}")

        print("Running Market Intelligence Agent...")
        mi_agent = MarketIntelligenceAgent()
        market_briefing = mi_agent.run("Scan the watchlist and assess open positions.", conn=conn)
        print(f"Market context: {market_briefing.get('market_context')}")

        print("Running Strategy Agent...")
        strategy_agent = StrategyAgent()
        candidates = strategy_agent.run(json.dumps(market_briefing), conn=conn)
        print(f"Candidates found: {len(candidates.get('candidates', []))}")

        if not candidates.get("candidates"):
            print(f"No trade candidates: {candidates.get('no_trade_reason')}")
            costs = get_daily_token_costs(conn, date.today().isoformat())
            print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
            notify_no_candidates(
                date.today().isoformat(),
                tldr=candidates.get("tldr", "conditions not met"),
                tickers_to_watch=candidates.get("tickers_to_watch", []),
                cost_usd=costs["cost_usd"],
            )
            return

        print("Running Risk Review Agent...")
        risk_agent = RiskReviewAgent()
        reviewed = risk_agent.run(json.dumps(candidates), conn=conn)
        print(f"Approved: {len(reviewed.get('approved', []))} | Rejected: {len(reviewed.get('rejected', []))}")

        if not reviewed.get("approved"):
            print("No trades approved by risk review.")
            costs = get_daily_token_costs(conn, date.today().isoformat())
            print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
            notify_no_approved(date.today().isoformat(), costs["cost_usd"])
            return

        print("Running Team Leader Agent...")
        pending_stops = {t["ticker"]: t["stop_loss"] for t in reviewed["approved"]}
        pending_targets = {t["ticker"]: t["take_profit"] for t in reviewed["approved"]}
        pending_atrs = {t["ticker"]: t["atr"] for t in reviewed["approved"] if t.get("atr") is not None}
        leader_agent = TeamLeaderAgent()
        decisions = leader_agent.run(
            json.dumps(reviewed),
            conn=conn,
            pending_stops=pending_stops,
            pending_targets=pending_targets,
            pending_atrs=pending_atrs,
            dry_run=dry_run,
        )
        print(f"Session summary: {decisions.get('summary')}")

        costs = get_daily_token_costs(conn, date.today().isoformat())
        print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
        notify_scan_complete(
            date=date.today().isoformat(),
            market_context=market_briefing.get("market_context", "unknown"),
            tldr=candidates.get("tldr", ""),
            approved=len(reviewed.get("approved", [])),
            rejected=len(reviewed.get("rejected", [])),
            decisions=decisions.get("decisions", []),
            cost_usd=costs["cost_usd"],
        )

    except Exception as e:
        print(f"SCAN ERROR: {e}")
        notify_error("morning_scan", traceback.format_exc())
    finally:
        if conn is not None:
            conn.close()


def run_position_monitor():
    if not is_trading_day():
        return
    conn = None
    try:
        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        print(f"=== Position monitor — {date.today()} {now} ===")
        conn = get_db()
        actions = run_monitor(conn)
        closed = [a for a in actions if a.action in ("close", "reconciled")]
        print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
        notify_monitor(date.today().isoformat(), now, len(actions), closed)
    except Exception as e:
        print(f"MONITOR ERROR: {e}")
        notify_error("position_monitor", traceback.format_exc())
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode == "scan":
        import argparse
        parser = argparse.ArgumentParser(prog="main.py scan")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")
        args = parser.parse_args(sys.argv[2:])
        run_morning_scan(dry_run=args.dry_run)
    elif mode == "monitor":
        run_position_monitor()
    elif mode == "backtest":
        import argparse
        from backtest.runner import run_backtest
        from config import settings as _s

        parser = argparse.ArgumentParser(prog="main.py backtest")
        parser.add_argument("--years", type=int, default=3)
        parser.add_argument("--ema-fast", type=int, default=_s.EMA_FAST, dest="ema_fast")
        parser.add_argument("--ema-slow", type=int, default=_s.EMA_SLOW, dest="ema_slow")
        parser.add_argument("--rsi-period", type=int, default=_s.RSI_PERIOD, dest="rsi_period")
        parser.add_argument("--rsi-lower", type=float, default=_s.RSI_LOWER, dest="rsi_lower")
        parser.add_argument("--rsi-upper", type=float, default=_s.RSI_UPPER, dest="rsi_upper")
        parser.add_argument("--volume-multiplier", type=float, default=_s.VOLUME_MULTIPLIER, dest="volume_multiplier")
        parser.add_argument("--atr-period", type=int, default=_s.ATR_PERIOD, dest="atr_period")
        parser.add_argument("--atr-multiplier", type=float, default=_s.ATR_STOP_MULTIPLIER, dest="atr_multiplier")
        parser.add_argument("--rr-ratio", type=float, default=_s.RR_RATIO_MIN, dest="rr_ratio")
        parser.add_argument("--max-hold-days", type=int, default=_s.MAX_HOLD_DAYS, dest="max_hold_days")
        parser.add_argument("--strict-crossover", action="store_true", default=_s.STRICT_CROSSOVER, dest="strict_crossover")
        parser.add_argument("--no-strict-crossover", action="store_false", dest="strict_crossover")
        parser.add_argument(
            "--portfolio",
            action="store_true",
            default=False,
            dest="portfolio",
            help="Run the portfolio-level simulator (MAX_POSITIONS-aware) instead of the per-ticker runner.",
        )
        args = parser.parse_args(sys.argv[2:])
        run_backtest(**vars(args))
    elif mode == "summary":
        conn = None
        try:
            conn = get_db()
            from tools.database import get_closed_trade_stats
            from tools.notifications import notify_performance_summary
            stats = get_closed_trade_stats(conn)
            print(f"Trailing {stats['days']}d: {stats['trade_count']} trades | "
                  f"Win rate: {stats['win_rate']:.1%} | "
                  f"PnL: ${stats['total_pnl_dollars']:+.2f} | "
                  f"Avg R: {stats['avg_r_multiple']:+.2f}")
            notify_performance_summary(stats)
        finally:
            if conn:
                conn.close()
    else:
        print(f"Unknown mode: {mode}. Use 'scan', 'monitor', 'backtest', or 'summary'")
