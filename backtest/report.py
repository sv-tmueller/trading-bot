from __future__ import annotations

from tools.notifications import notify_backtest


def _fmt_pf(pf) -> str:
    if pf is None:
        return "  n/a"
    if pf == float("inf"):
        return "  inf"
    return f"{pf:>5.2f}"


def _fmt_pct(value) -> str:
    if value is None:
        return "   n/a"
    return f"{value:>+5.1f}%"


def _fmt_ratio(value) -> str:
    if value is None:
        return "  n/a"
    return f"{value:>4.2f}"


def format_terminal(result: dict) -> str:
    p = result["params"]
    agg = result["aggregate"]

    header = (
        f"Backtest: {result['period']}  |  "
        f"EMA {p['ema_fast']}/{p['ema_slow']}  "
        f"RSI {p['rsi_lower']:.0f}-{p['rsi_upper']:.0f}  "
        f"Hold ≤{p['max_hold_days']}d"
    )
    note = "(each ticker independent — max-positions constraint not simulated)"
    warn = "⚠️  Single-year backtest — may not reflect robustness across regimes." if p["years"] == 1 else ""
    col = (
        f"{'Ticker':<8} {'Trades':>6} {'Win%':>6} {'Return':>9} {'Max DD':>8} "
        f"{'PF':>5} {'Win $':>6} {'Loss $':>6}"
    )
    sep = "-" * len(col)

    rows = [
        f"{ticker:<8} {s['trades']:>6} "
        f"{s['win_rate'] * 100:>5.1f}% "
        f"{s['total_return'] * 100:>+8.1f}% "
        f"{s['max_drawdown'] * 100:>7.1f}% "
        f"{_fmt_pf(s.get('profit_factor'))} "
        f"{_fmt_pct(s.get('avg_winner_pct'))} "
        f"{_fmt_pct(s.get('avg_loser_pct'))}"
        for ticker, s in result["tickers"].items()
    ]
    total = (
        f"{'TOTAL':<8} {agg['trades']:>6} "
        f"{agg['win_rate'] * 100:>5.1f}% "
        f"{agg['total_return'] * 100:>+8.1f}% "
        f"{agg['max_drawdown'] * 100:>7.1f}% "
        f"{_fmt_pf(agg.get('profit_factor'))} "
        f"{_fmt_pct(agg.get('avg_winner_pct'))} "
        f"{_fmt_pct(agg.get('avg_loser_pct'))}"
    )

    agg_block = [
        "",
        "Aggregate (pooled across all trades):",
        f"  Profit factor:       {_fmt_pf(agg.get('profit_factor')).strip()}",
        f"  Expectancy / trade:  {_fmt_pct(agg.get('expectancy_pct')).strip()}",
        f"  Winner : Loser:      {_fmt_ratio(agg.get('winner_loser_ratio')).strip()}",
    ]

    parts = [header, note]
    if warn:
        parts.append(warn)
    parts += ["", col, sep] + rows + [sep, total] + agg_block
    return "\n".join(parts)
