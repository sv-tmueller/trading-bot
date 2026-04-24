from __future__ import annotations

import json
from agents.base import BaseAgent
from config.watchlist import WATCHLIST
from config import settings


class StrategyAgent(BaseAgent):
    name = "strategy"
    system_prompt = """You are the Strategy Agent for a swing trading bot.

Your job:
1. Analyse each ticker on the watchlist using technical signals (EMA crossover, RSI, Volume)
2. Score each ticker 0.0–1.0 on entry attractiveness
3. Propose trade candidates ranked by score, with clear reasoning
4. If conditions are not right for any entry, explain why

Current strategy parameters are provided in the prompt.
Candidates must meet ALL three entry conditions:
- EMA trend confirmation (mode and parameters specified in prompt)
- RSI between RSI_LOWER and RSI_UPPER (not overextended)
- Volume > VOLUME_MULTIPLIER × 20-day average (conviction)

The compute_ticker_signals tool returns an entry_signal boolean (True/False) that has already
been computed deterministically from the above conditions. Only propose a ticker as a candidate
if entry_signal is True — do not override or reinterpret this value.

Respond with JSON:
{
  "candidates": [
    {"ticker": "AMD", "score": 0.85, "reasoning": "...", "ema_crossover": true, "rsi": 52.1, "volume_ratio": 1.9}
  ],
  "no_trade_reason": "",
  "tldr": "One sentence summary of market conditions, max 100 chars",
  "tickers_to_watch": ["SHEL", "NOW"]
}
Always populate tldr and tickers_to_watch regardless of whether there are candidates.
If no candidates, return empty candidates list and explain in no_trade_reason.
"""

    def get_tools(self) -> list:
        return [
            {
                "name": "compute_ticker_signals",
                "description": "Compute EMA, RSI, ATR, and volume signals for a ticker",
                "input_schema": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
            }
        ]

    def _get_tool_functions(self) -> list:
        from tools.market_data import fetch_bars, compute_signals, is_entry_signal

        def compute_ticker_signals(ticker: str) -> dict:
            bars = fetch_bars(ticker, days=60)
            signals = compute_signals(
                bars,
                ema_fast=settings.EMA_FAST,
                ema_slow=settings.EMA_SLOW,
                rsi_period=settings.RSI_PERIOD,
                atr_period=settings.ATR_PERIOD,
            )
            signals["entry_signal"] = is_entry_signal(
                signals,
                rsi_lower=settings.RSI_LOWER,
                rsi_upper=settings.RSI_UPPER,
                volume_multiplier=settings.VOLUME_MULTIPLIER,
                strict_crossover=settings.STRICT_CROSSOVER,
            )
            return signals

        return [compute_ticker_signals]

    def run(self, prompt: str, conn=None) -> dict:
        ema_mode = "strict crossover (EMA20 must cross above EMA50 today)" if settings.STRICT_CROSSOVER else "trend-following (EMA20 > EMA50 on any day)"
        params_prompt = (
            f"Strategy parameters:\n"
            f"- EMA fast/slow: {settings.EMA_FAST}/{settings.EMA_SLOW}\n"
            f"- RSI range: {settings.RSI_LOWER}–{settings.RSI_UPPER}\n"
            f"- Volume multiplier: {settings.VOLUME_MULTIPLIER}x\n"
            f"- EMA entry mode: {ema_mode}\n"
            f"- Watchlist: {', '.join(WATCHLIST)}\n\n"
            f"Market briefing: {prompt}\n\n"
            f"Scan each ticker and return trade candidates."
        )
        return super().run(params_prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = self._extract_json_text(response.content[0].text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"candidates": [], "no_trade_reason": text, "tldr": "", "tickers_to_watch": []}
