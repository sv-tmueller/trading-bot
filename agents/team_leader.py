from __future__ import annotations

import json
from datetime import date, datetime
from agents.base import BaseAgent


class TeamLeaderAgent(BaseAgent):
    name = "team_leader"
    system_prompt = """You are the Team Leader Agent — the final decision-maker for a swing trading bot.

You receive consolidated reports from three specialist agents:
- Market Intelligence: current market conditions and flagged positions
- Strategy: scored trade candidates with technical reasoning
- Risk Review: approved candidates with exact position sizes and risk parameters

Your job:
1. Review all agent reports holistically
2. Make final go/no-go decision on each approved candidate
3. Place orders for approved trades using the place_order tool
4. Handle any flagged positions from Market Intelligence (close if needed)
5. Write a clear decision log explaining every action taken

You are the only agent authorised to place or close orders.

If a place_order tool result has `status: "dry_run_simulated"`, describe the outcome in conditional/future tense (e.g. 'would have bought' rather than 'bought'). Do NOT say the order was executed.

Respond with JSON:
{
  "decisions": [
    {"ticker": "AMD", "action": "buy", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "reasoning": "..."}
  ],
  "summary": "brief summary of the session"
}
"""

    def __init__(self) -> None:
        super().__init__()
        self._conn = None
        self._pending_stops: dict = {}
        self._pending_targets: dict = {}
        self._pending_atrs: dict = {}
        self._pending_indicators: dict = {}
        self._dry_run: bool = False

    def get_tools(self) -> list:
        return [
            {
                "name": "place_order",
                "description": "Place a market order to buy or sell shares",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "shares": {"type": "integer"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                    },
                    "required": ["ticker", "shares", "side"],
                },
            },
            {
                "name": "close_position",
                "description": "Close an open position entirely",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "enum": ["stop_loss", "take_profit", "trend_reversal", "max_hold", "manual"],
                            "description": "Why this position is being closed",
                        },
                    },
                    "required": ["ticker"],
                },
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.broker import place_market_order, close_position as broker_close_position
        from tools.broker import get_current_price, get_alpaca_positions, get_portfolio_value
        from tools.broker import BrokerSubmitError
        from tools.database import insert_trade, get_open_trades, close_trade, insert_signal
        from tools.risk import check_exposure_for_new_order, validate_bracket_params
        from tools.notifications import notify_order_rejected, notify_error
        from config import settings
        conn = self._conn
        pending_stops = self._pending_stops
        pending_targets = self._pending_targets
        pending_atrs = self._pending_atrs
        pending_indicators = self._pending_indicators
        dry_run = self._dry_run

        def _persist_signal_row(ticker: str, trade_id, triggered_entry: int) -> None:
            """Write one signals row, swallowing DB errors so the order path continues.

            Per issue #136: this is purely observability — the order has already been
            placed (or rejected) by the time we get here. Losing the audit row must
            never crash the scan or undo the trade. Mirrors the failure-isolation
            pattern in `_persist_action_row` from PR #140.
            """
            indicators = pending_indicators.get(ticker, {})
            try:
                insert_signal(conn, {
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "date": date.today().isoformat(),
                    "ema_fast": indicators.get("ema_fast"),
                    "ema_slow": indicators.get("ema_slow"),
                    "rsi": indicators.get("rsi"),
                    "volume_ratio": indicators.get("volume_ratio"),
                    "signal_score": indicators.get("signal_score"),
                    "triggered_entry": triggered_entry,
                })
            except Exception as e:
                notify_error(
                    "team_leader",
                    f"insert_signal failed for {ticker} "
                    f"(trade_id={trade_id}, triggered_entry={triggered_entry}): "
                    f"{type(e).__name__}: {e}",
                )

        def place_order(ticker: str, shares: int, side: str) -> dict:
            price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk

            # Deterministic exposure gate — runs on every buy, including dry-run.
            # The LLM cannot bypass this; even if Team Leader hallucinates a clean
            # portfolio we recompute current notional from broker truth here. Sells
            # skip the gate because they reduce, not add, exposure.
            if side == "buy":
                try:
                    portfolio_value = get_portfolio_value()
                    open_positions = get_alpaca_positions()
                    current_notional = sum(
                        p["qty"] * p["avg_entry_price"] for p in open_positions
                    )
                except Exception as e:
                    # Fail-closed: if we can't verify exposure, reject. Better
                    # to skip a trade than over-deploy.
                    reason = f"exposure check failed: {e}"
                    print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                    notify_order_rejected(ticker, shares, reason)
                    if not dry_run:
                        _persist_signal_row(ticker, None, 0)
                    return {"order_id": None, "status": "rejected", "reason": reason}

                candidate_notional = shares * price
                gate = check_exposure_for_new_order(
                    current_notional=current_notional,
                    candidate_notional=candidate_notional,
                    portfolio_value=portfolio_value,
                    max_exposure=settings.MAX_PORTFOLIO_EXPOSURE,
                )
                if not gate["can_trade"]:
                    reason = gate["reason"]
                    print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                    notify_order_rejected(ticker, shares, reason)
                    if not dry_run:
                        _persist_signal_row(ticker, None, 0)
                    return {"order_id": None, "status": "rejected", "reason": reason}

            # Bracket pricing: recompute stop/target locally from the fresh
            # quote so the broker-side legs are anchored to a current price
            # (not the LLM's stale prior-close). Falls back to the LLM-supplied
            # values if no ATR was passed through (sells, missing data).
            bracket_stop = None
            bracket_target = None
            if side == "buy":
                atr = pending_atrs.get(ticker)
                if atr is not None and atr > 0:
                    stop_distance = atr * settings.ATR_STOP_MULTIPLIER
                    bracket_stop = round(price - stop_distance, 4)
                    bracket_target = round(price + stop_distance * settings.RR_RATIO_MIN, 4)
                else:
                    # Fallback: scale LLM-supplied prices to the fresh quote
                    # so R:R math is at least roughly preserved.
                    bracket_stop = pending_stops.get(ticker)
                    bracket_target = pending_targets.get(ticker)

                # Reject malformed brackets before they reach the broker — the
                # Alpaca SDK does not validate stop/target ordering.
                bracket_check = validate_bracket_params(price, bracket_stop, bracket_target)
                if not bracket_check["valid"]:
                    reason = f"invalid bracket: {bracket_check['reason']}"
                    print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                    notify_order_rejected(ticker, shares, reason)
                    if not dry_run:
                        _persist_signal_row(ticker, None, 0)
                    return {"order_id": None, "status": "rejected", "reason": reason}

            # Dry-run skips ONLY the broker SUBMIT and DB INSERT — all
            # deterministic checks above ran the same as a live run, so a
            # `--dry-run` smoke test exercises the full safety stack.
            if dry_run:
                print(f"[DRY RUN] would {side} {shares} shares of {ticker}")
                return {
                    "order_id": "DRY_RUN",
                    "fill_price": None,
                    "status": "dry_run_simulated",
                    "note": "no order was placed; this is a dry run",
                }

            try:
                order_result = place_market_order(
                    ticker,
                    shares,
                    side,
                    stop_price=bracket_stop,
                    take_profit_price=bracket_target,
                )
            except BrokerSubmitError as e:
                reason = f"broker rejected: {e}"
                print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                notify_order_rejected(ticker, shares, reason)
                if side == "buy":
                    _persist_signal_row(ticker, None, 0)
                return {"order_id": None, "status": "rejected", "reason": reason}
            order_id = order_result["order_id"]
            trade_id = None
            if side == "buy":
                # Issue #132: prefer the broker's actual filled_avg_price (now polled in
                # tools.broker.place_market_order) so trades.entry_price reflects the real
                # fill, not the pre-order quote. Fallback to the pre-order quote only on
                # poll timeout (rare during regular hours) so the trade row is never lost.
                fill_price = order_result.get("fill_price")
                if fill_price is not None:
                    entry_price = fill_price
                else:
                    entry_price = price
                    print(
                        f"[place_order] WARN {ticker} {shares}sh — broker fill not reported within "
                        f"poll window; storing pre-order quote {price:.4f} as entry_price (#132)"
                    )
                trade_id = insert_trade(conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": entry_price,
                    "shares": shares,
                    "stop_loss": bracket_stop if bracket_stop is not None else (pending_stops.get(ticker, entry_price * 0.97)),
                    "take_profit": bracket_target if bracket_target is not None else (pending_targets.get(ticker, entry_price * 1.06)),
                })
                _persist_signal_row(ticker, trade_id, 1)
            return {"order_id": order_id, "status": "submitted"}

        def close_position(ticker: str, reason: str = "manual") -> dict:
            if dry_run:
                print(f"[DRY RUN] would close {ticker} ({reason})")
                return {"order_id": "dry-run", "status": "dry-run"}
            price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk
            order_id = broker_close_position(ticker)
            today = date.today().isoformat()
            open_trades = get_open_trades(conn)
            trade = next((t for t in open_trades if t["ticker"] == ticker), None)
            if trade is not None:
                entry_price = trade["entry_price"]
                stop_distance = entry_price - trade["stop_loss"]
                pnl_dollars = (price - entry_price) * trade["shares"]
                r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
                entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
                today_date = datetime.strptime(today, "%Y-%m-%d").date()
                hold_days = (today_date - entry_date).days
                close_trade(conn, trade["id"], {
                    "exit_date": today,
                    "exit_price": price,
                    "exit_reason": reason,
                    "pnl_dollars": round(pnl_dollars, 2),
                    "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                    "hold_days": hold_days,
                    "r_multiple": round(r_multiple, 3),
                })
            return {"order_id": order_id, "status": "closed"}

        return [place_order, close_position]

    def run(self, prompt: str, conn=None, pending_stops: dict = None, pending_targets: dict = None, pending_atrs: dict = None, pending_indicators: dict = None, dry_run: bool = False) -> dict:
        self._conn = conn
        self._pending_stops = pending_stops or {}
        self._pending_targets = pending_targets or {}
        self._pending_atrs = pending_atrs or {}
        self._pending_indicators = pending_indicators or {}
        self._dry_run = dry_run
        return super().run(prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = self._extract_json_text(response.content[0].text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"decisions": [], "summary": text}
