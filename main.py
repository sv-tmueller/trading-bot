from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
import pandas_market_calendars as mcal
from datetime import date
from pathlib import Path
from typing import Optional

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
    notify_panic,
)
from tools.ibkr_broker import (
    connect_ibkr,
    cancel_all_orders,
    liquidate,
    get_position,
    IBKRConnectionError,
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
        # Indicator snapshot for the signals-table audit row written from
        # team_leader.place_order (issue #136). Built from the strategy agent's
        # candidate dict (which carries rsi/volume_ratio/score from the
        # deterministic compute_ticker_signals tool), keyed by ticker so each
        # place_order tool call can look up its own indicators. Indicators the
        # strategy candidate doesn't surface (ema_fast/ema_slow numeric values)
        # land as NULL in the row and that's fine — the schema permits it.
        pending_indicators = {
            c["ticker"]: {
                "ema_fast": c.get("ema_fast"),
                "ema_slow": c.get("ema_slow"),
                "rsi": c.get("rsi"),
                "volume_ratio": c.get("volume_ratio"),
                "signal_score": c.get("score"),
            }
            for c in candidates.get("candidates", [])
        }
        leader_agent = TeamLeaderAgent()
        decisions = leader_agent.run(
            json.dumps(reviewed),
            conn=conn,
            pending_stops=pending_stops,
            pending_targets=pending_targets,
            pending_atrs=pending_atrs,
            pending_indicators=pending_indicators,
            dry_run=dry_run,
        )
        print(f"Session summary: {decisions.get('summary')}")

        costs = get_daily_token_costs(conn, date.today().isoformat())
        print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
        # Issue #139: prefer the deterministic per-ticker outcome counts captured
        # inside team_leader.place_order over the risk_review-level approved/rejected
        # tally. risk_review's `approved` count means "passed risk review", not
        # "order placed" — the exposure gate inside team_leader can still reject
        # an approved candidate (live evidence: 2026-05-04 AMD, 2026-05-05
        # AAPL/SHEL). The operator-facing summary line MUST reflect what the
        # broker actually saw, not what the LLM said in prose.
        order_outcomes = decisions.get("order_outcomes", {})
        deterministic_buy_count = len(order_outcomes.get("buy", []))
        deterministic_dry_run_count = len(order_outcomes.get("dry_run", []))
        deterministic_rejected_count = len(order_outcomes.get("rejected", []))
        # In dry-run we count "would have placed" as approved so the summary
        # still reflects intent. In live, only actual fills count.
        approved_for_summary = deterministic_buy_count + (
            deterministic_dry_run_count if dry_run else 0
        )
        notify_scan_complete(
            date=date.today().isoformat(),
            market_context=market_briefing.get("market_context", "unknown"),
            tldr=candidates.get("tldr", ""),
            approved=approved_for_summary,
            rejected=deterministic_rejected_count,
            decisions=decisions.get("decisions", []),
            cost_usd=costs["cost_usd"],
            dry_run=dry_run,
            order_outcomes=order_outcomes,
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


_REPO_ROOT = Path(__file__).resolve().parent


def _pause_trading_in_env(env_path: Optional[Path] = None) -> bool:
    """Atomically write `TRADING_PAUSED=true` to .env (replace if present, append otherwise).

    Uses a temp-file + os.replace pattern so a crash mid-write can never leave
    a partially rewritten .env on disk. Returns True if the file changed,
    False if `TRADING_PAUSED=true` was already present (no-op / idempotent).

    Defaults to the repo-root `.env` (next to this file) so `python /opt/trading-bot/main.py
    panic --pause` works correctly regardless of the caller's cwd. Without this anchor,
    invoking from `/tmp` or `/root` would write a stray `.env` to that directory and the
    live bot would keep scanning unpaused — silent failure during incident response.
    """
    env_path = env_path or (_REPO_ROOT / ".env")
    if env_path.exists():
        original = env_path.read_text()
    else:
        original = ""
    lines = original.splitlines()
    new_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TRADING_PAUSED="):
            found = True
            new_lines.append("TRADING_PAUSED=true")
        else:
            new_lines.append(line)
    if not found:
        new_lines.append("TRADING_PAUSED=true")
    new_content = "\n".join(new_lines)
    if original.endswith("\n") or not original:
        new_content += "\n"
    if new_content == original:
        return False  # already paused — idempotent no-op
    tmp_path = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp_path.write_text(new_content)
    os.replace(str(tmp_path), str(env_path))
    return True


def run_panic(
    cancel_orders: bool = False,
    liquidate: bool = False,
    pause: bool = False,
    confirm: bool = False,
) -> int:
    """Deterministic incident-response CLI — see `main.py panic --help`.

    Returns a Unix-style exit code (0 = success, non-zero = error). No LLM
    calls anywhere in this path: the CLI **is** the deterministic safety net
    referenced in the architectural invariants. Order of operations when both
    --cancel-orders and --liquidate are set: cancel orders FIRST so any
    unfilled bracket entries don't race the liquidation.
    """
    # The kwarg ``liquidate`` shadows the module-level import of the same name
    # within this function's scope. Resolve broker-call attributes through the
    # module dict at call time so test patches on ``main.connect_ibkr`` /
    # ``main.cancel_all_orders`` / ``main.liquidate`` / ``main.get_position``
    # take effect (the LEGB lookup would otherwise miss them).
    _mod = sys.modules[__name__]

    # `--liquidate` without `--confirm` must NOT touch the broker beyond a
    # read-only position query for the preview. Post a dry-run Discord alert
    # and exit non-zero so a script invoking us catches the missing flag.
    if liquidate and not confirm:
        print("DRY RUN — would liquidate all positions. Re-run with --confirm to execute.")
        qty = 0
        try:
            ib_preview = _mod.connect_ibkr(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                client_id=settings.IBKR_CLIENT_ID,
            )
            try:
                qty = _mod.get_position(ib_preview, settings.BOT_TICKER)
            finally:
                try:
                    ib_preview.disconnect()
                except Exception:
                    pass
        except Exception as e:
            print(f"[panic] could not query position for dry preview: {e}")
            qty = 0
        positions: list = []
        if qty > 0:
            positions = [{"ticker": settings.BOT_TICKER, "qty": qty}]
            print(f"  would close: {settings.BOT_TICKER} qty={qty}")
        try:
            notify_panic("liquidate", positions, dry_run=True)
        except Exception as e:
            print(f"[panic] notify_panic failed: {e}")
        return 2

    if not (cancel_orders or liquidate or pause):
        print("Usage: python main.py panic [--cancel-orders] [--liquidate --confirm] [--pause]")
        return 1

    flags = []
    if cancel_orders:
        flags.append("--cancel-orders")
    if liquidate:
        flags.append("--liquidate")
    if pause:
        flags.append("--pause")
    if confirm:
        flags.append("--confirm")
    intent = "cancel_orders=" + str(cancel_orders) + " liquidate=" + str(liquidate) + " pause=" + str(pause)

    # Single connection held across audit INSERT, broker actions, and the final UPDATE so
    # the same row records both intent (BEFORE the broker call — preserves the partial-recovery
    # property even if a later broker call kills the process) and outcome (AFTER each action,
    # so forensics doesn't have to cross-reference Discord). Closed in the outer finally.
    conn = None
    audit_row_id = None
    try:
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO agent_logs
                   (cycle_date, agent_name, input_summary, output_summary, full_reasoning,
                    tokens_used, input_tokens, output_tokens)
               VALUES
                   (:cycle_date, :agent_name, :input_summary, :output_summary, :full_reasoning,
                    :tokens_used, :input_tokens, :output_tokens)""",
            {
                "cycle_date": date.today().isoformat(),
                "agent_name": "panic",
                "input_summary": " ".join(flags),
                "output_summary": intent,
                "full_reasoning": "deterministic CLI; no LLM",
                "tokens_used": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
        )
        conn.commit()
        audit_row_id = cur.lastrowid
    except Exception as e:
        print(f"[panic] audit log write failed: {e}")

    exit_code = 0
    result_parts: list = []

    ib = None
    try:
        # Connect once if any broker action is requested. Connection failure
        # fails the affected branches CLOSED — the pause branch is unaffected.
        if cancel_orders or (liquidate and confirm):
            try:
                ib = _mod.connect_ibkr(
                    host=settings.IBKR_HOST,
                    port=settings.IBKR_PORT,
                    client_id=settings.IBKR_CLIENT_ID,
                )
            except IBKRConnectionError as e:
                tb = traceback.format_exc()
                print(f"[panic] TWS connection failed: {e}")
                result_parts.append(f"connect=fail({type(e).__name__})")
                try:
                    notify_error("panic", f"connect_ibkr failed: {e}\n\n{tb}")
                except Exception:
                    pass
                exit_code = 1
                ib = None

        # 1. Cancel orders FIRST so unfilled entries don't race the liquidation.
        if cancel_orders:
            if ib is None:
                # Connection failed above — record the skip. notify_error already fired.
                result_parts.append("cancel-orders=fail(no_ib)")
            else:
                try:
                    n = _mod.cancel_all_orders(ib)
                    print(f"[panic] cancelled {n} order(s)")
                    result_parts.append(f"cancel-orders=ok({n})")
                    try:
                        notify_panic("cancel-orders", [{"count": n}])
                    except Exception as e:
                        print(f"[panic] notify_panic failed: {e}")
                except Exception as e:
                    tb = traceback.format_exc()
                    print(f"[panic] cancel_all_orders failed: {e}")
                    result_parts.append(f"cancel-orders=fail({type(e).__name__})")
                    try:
                        notify_error("panic", f"cancel_all_orders failed: {e}\n\n{tb}")
                    except Exception:
                        pass
                    exit_code = 1

        # 2. Liquidate the single bot position. The new bot is single-vehicle
        # (settings.BOT_TICKER), so liquidate() returns Optional[dict] for that
        # one symbol — None means no position (success path, not failure).
        if liquidate and confirm:
            if ib is None:
                result_parts.append("liquidate=fail(no_ib)")
            else:
                try:
                    fill = _mod.liquidate(ib, symbol=settings.BOT_TICKER)
                    if fill:
                        print(f"[panic] liquidated {fill['qty']} @ {fill['fill_price']}")
                        result_parts.append(f"liquidate=ok(qty={fill['qty']}@{fill['fill_price']})")
                        try:
                            notify_panic("liquidate", [{
                                "ticker": settings.BOT_TICKER,
                                "qty": fill["qty"],
                                "fill_price": fill["fill_price"],
                            }])
                        except Exception as e:
                            print(f"[panic] notify_panic failed: {e}")
                    else:
                        print("[panic] no position to liquidate")
                        result_parts.append("liquidate=ok(no_position)")
                        try:
                            notify_panic("liquidate", [])
                        except Exception as e:
                            print(f"[panic] notify_panic failed: {e}")
                except Exception as e:
                    tb = traceback.format_exc()
                    print(f"[panic] liquidate failed: {e}")
                    result_parts.append(f"liquidate=fail({type(e).__name__})")
                    try:
                        notify_error("panic", f"liquidate failed: {e}\n\n{tb}")
                    except Exception:
                        pass
                    exit_code = 1

        # 3. Pause new entries (idempotent — no-op if already paused).
        if pause:
            try:
                changed = _pause_trading_in_env()
                msg = "TRADING_PAUSED=true written to .env" if changed else "TRADING_PAUSED=true already set (no-op)"
                print(f"[panic] {msg}")
                result_parts.append("pause=ok(written)" if changed else "pause=ok(already-set)")
                try:
                    notify_panic("pause", [{"status": msg}])
                except Exception as e:
                    print(f"[panic] notify_panic failed: {e}")
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[panic] pause failed: {e}")
                result_parts.append(f"pause=fail({type(e).__name__})")
                try:
                    notify_error("panic", f"pause failed: {e}\n\n{tb}")
                except Exception:
                    pass
                exit_code = 1
    finally:
        # Always disconnect IB if we connected, including error paths.
        if ib is not None:
            try:
                ib.disconnect()
            except Exception:
                pass
        # Update the same audit row with the actual outcome — single row per panic
        # invocation, intent + result both captured.
        if conn is not None:
            if audit_row_id is not None:
                try:
                    summary = intent + " | result: " + (" ".join(result_parts) if result_parts else "no-actions")
                    conn.execute(
                        "UPDATE agent_logs SET output_summary = :s WHERE id = :id",
                        {"s": summary, "id": audit_row_id},
                    )
                    conn.commit()
                except Exception as e:
                    print(f"[panic] audit log update failed: {e}")
            try:
                conn.close()
            except Exception:
                pass

    return exit_code


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
    elif mode == "panic":
        import argparse
        parser = argparse.ArgumentParser(
            prog="main.py panic",
            description="Deterministic incident-response CLI: cancel orders, liquidate positions, pause new entries.",
        )
        parser.add_argument("--cancel-orders", action="store_true", dest="cancel_orders",
                            help="Cancel every open order at the broker (parent + bracket children).")
        parser.add_argument("--liquidate", action="store_true", dest="liquidate",
                            help="Market-close every open position. REQUIRES --confirm to actually run.")
        parser.add_argument("--pause", action="store_true", dest="pause",
                            help="Set TRADING_PAUSED=true in .env (atomic) so the next scan exits before placing entries.")
        parser.add_argument("--confirm", action="store_true", dest="confirm",
                            help="Mandatory companion to --liquidate. Without it, --liquidate prints a dry preview and exits non-zero.")
        args = parser.parse_args(sys.argv[2:])
        sys.exit(run_panic(
            cancel_orders=args.cancel_orders,
            liquidate=args.liquidate,
            pause=args.pause,
            confirm=args.confirm,
        ))
    else:
        print(f"Unknown mode: {mode}. Use 'scan', 'monitor', 'backtest', 'summary', or 'panic'")
