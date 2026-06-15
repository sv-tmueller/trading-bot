# Week YYYY-Www (Mon DD MMM – Fri DD MMM YYYY)

<!-- Replace the title with the actual ISO week and date range, e.g.:
     # Week 2026-W24 (Mon 8 Jun – Fri 12 Jun 2026) -->

---

## Regime / signal at week open

<!-- State the signal the bot was acting on at Monday open. -->

- **SPY close (previous Friday):** $___.___ 
- **SPY 200-DMA:** $___.___ 
- **Signal:** LONG | CASH
- **Kill-switch state:** inactive | active (fired YYYY-MM-DD)

---

## Action taken & fills

<!-- Describe what the bot did this week. If no trades, write "No trades — regime unchanged." -->

| Date | Side | Symbol | Qty | Fill price | Reason |
|------|------|--------|-----|-----------|--------|
|      |      |        |     |           |        |

<!-- Include any kill-switch activity, pause/resume events, or manual interventions here. -->

---

## Realized P/L for the week

<!-- P/L from positions closed this week. If the position was held open all week with no trade, note the unrealized change for context but clearly label it unrealized. -->

- **Realized P/L:** $___.___ ( ___.___ %)
- **Unrealized P/L (position held):** $___.___ ( ___.___ %) — for context only

---

## Running drawdown from rolling high

<!-- The kill-switch tracks drawdown from the rolling high over KILL_SWITCH_LOOKBACK_DAYS.
     Record the state at week close. -->

- **Position:** LONG (UPRO) | CASH
- **Rolling high (reference price):** $___.___ 
- **Current price / last fill:** $___.___ 
- **Drawdown from rolling high:** ___.___ %
- **Kill-switch threshold:** ___.___ % (from config)

---

## Benchmark comparison

<!-- How did the bot's return for the week compare to the buy-and-hold baseline?
     Use the same period (Mon open to Fri close) for both. -->

| Metric | Bot | Buy-and-hold SPY | Buy-and-hold ETF (BOT_BENCHMARK) |
|--------|-----|-----------------|----------------------------------|
| Week return | ___.___ % | ___.___ % | ___.___ % |
| YTD return | ___.___ % | ___.___ % | ___.___ % |
| Max drawdown (rolling) | ___.___ % | ___.___ % | ___.___ % |

<!-- "Buy-and-hold" means fully invested since the bot's live start date, no rebalancing. -->

---

## Notes & decisions

<!-- Anything that does not fit the structured sections above:
     - Market context (macro events, unusual volatility, earnings that moved SPY).
     - Config changes made this week and why (link to docs/decisions/ entry if one was written).
     - Observations about signal quality or bot behaviour.
     - Questions or concerns to revisit next week.
     If nothing noteworthy, write "_Uneventful week — no notes._" -->
