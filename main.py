"""Top-level CLI entry point for the rules-engine trading bot.

Modes:
  - ``panic``    — deterministic incident-response: cancel orders, liquidate, pause.
  - ``summary``  — print trailing 30-day trade stats; no LLM, no broker.
  - ``backtest`` — wraps ``backtest/regime.py::main_cli`` for ad-hoc runs.
  - ``scan``     — REMOVED in 2026-05-07 pivot (was the LLM agent pipeline).
  - ``monitor``  — REMOVED in 2026-05-07 pivot (now lives in ``monitor/kill_switch.py``).

The daily entry script the production cron actually invokes is
``daily_check.py``; ``main.py`` is reserved for operator tools (``panic``,
``summary``) and ad-hoc backtests.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings
from storage.init_db import init_db, DB_PATH
from tools.database import insert_audit_log, update_audit_log
from tools.notifications import notify_error, notify_panic
from tools.ibkr_broker import (
    connect_ibkr,
    cancel_all_orders,
    liquidate,
    get_position,
    IBKRConnectionError,
)


def get_db() -> sqlite3.Connection:
    """Open the bot's SQLite DB with FKs + row factory configured."""
    init_db(str(DB_PATH))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    started = _now_iso()
    try:
        conn = get_db()
        audit_row_id = insert_audit_log(
            conn,
            script_name="panic",
            started_at=started,
            notes=" ".join(flags) + " | " + intent,
        )
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
                    outcome = "success" if exit_code == 0 else f"error:exit_code={exit_code}"
                    notes = intent + " | result: " + (" ".join(result_parts) if result_parts else "no-actions")
                    update_audit_log(
                        conn,
                        rowid=audit_row_id,
                        finished_at=_now_iso(),
                        outcome=outcome,
                        notes=notes,
                    )
                except Exception as e:
                    print(f"[panic] audit log update failed: {e}")
            try:
                conn.close()
            except Exception:
                pass

    return exit_code


def _run_summary() -> int:
    """Print trailing 30-day trade stats. Replaces the LLM-era token-cost summary.

    Pulls from the post-pivot ``trades`` table (symbol/side/qty/fill_price/...)
    rather than the legacy ATR-style schema that ``get_closed_trade_stats``
    targeted. Inlined here so deletion of that helper in Task 14 doesn't
    break ``main.py summary``.
    """
    conn = None
    try:
        conn = get_db()
        stats = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN reason = 'kill_switch' THEN 1 ELSE 0 END) AS ks_count
            FROM trades
            WHERE created_at >= datetime('now', '-30 days')
            """
        ).fetchone()
        n = stats["n"] or 0
        ks = stats["ks_count"] or 0
        print(f"Trailing 30d: {n} trades  ({ks} kill-switch)")
    finally:
        if conn:
            conn.close()
    return 0


def _run_backtest(argv: list[str]) -> int:
    """Wrap ``backtest/regime.py::main_cli`` so ``main.py backtest`` keeps working
    after the legacy per-ticker / portfolio backtesters were dropped in #200.

    All ``backtest`` subcommand args are forwarded to ``regime.main_cli`` via
    ``sys.argv``; we restore the original ``sys.argv`` after so the caller's
    state is untouched.
    """
    from backtest.regime import main_cli

    saved_argv = sys.argv
    try:
        sys.argv = ["backtest/regime.py", *argv]
        main_cli()
    finally:
        sys.argv = saved_argv
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher. Returns Unix exit code (0 = success).

    Modes:
      - ``panic``    — operator-driven incident response (no LLM, no auto).
      - ``summary``  — trailing 30-day stats (no LLM, no broker).
      - ``backtest`` — regime-filter backtester (calls ``backtest/regime.py``).
      - ``scan`` / ``monitor`` — REMOVED in the 2026-05-07 pivot. Returns 2 with
        a deprecation message pointing at ``daily_check.py`` and
        ``monitor/kill_switch.py``.
    """
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv else None
    rest = argv[1:] if argv else []

    if mode == "scan":
        print("'scan' mode removed in 2026-05-07 pivot.")
        print("The bot now runs daily_check.py directly via cron — no LLM agents.")
        print("See: docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md")
        return 2

    elif mode == "monitor":
        print("'monitor' mode removed in 2026-05-07 pivot.")
        print("Hourly drawdown protection now lives in monitor/kill_switch.py")
        print("(invoked directly by cron). See spec for details.")
        return 2

    elif mode == "backtest":
        return _run_backtest(rest)

    elif mode == "summary":
        return _run_summary()

    elif mode == "panic":
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
        args = parser.parse_args(rest)
        return run_panic(
            cancel_orders=args.cancel_orders,
            liquidate=args.liquidate,
            pause=args.pause,
            confirm=args.confirm,
        )

    else:
        if mode is None:
            print("Usage: python main.py {backtest|summary|panic}")
        else:
            print(f"Unknown mode: {mode}. Use 'backtest', 'summary', or 'panic'")
        return 2


if __name__ == "__main__":
    sys.exit(main())
