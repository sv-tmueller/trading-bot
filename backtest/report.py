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


def format_portfolio(result: dict, *, max_trade_rows: int = 20, max_rejection_rows: int = 20) -> str:
    """Format a portfolio-level backtest result for terminal output."""
    p = result["params"]
    agg = result["aggregate"]

    header = (
        f"Portfolio backtest: {result['period']}  |  "
        f"EMA {p['ema_fast']}/{p['ema_slow']}  "
        f"RSI {p['rsi_lower']:.0f}-{p['rsi_upper']:.0f}  "
        f"Hold ≤{p['max_hold_days']}d"
    )
    note = "(single shared equity, MAX_POSITIONS + exposure gate enforced)"

    col = (
        f"{'Metric':<22} {'Value':>14}"
    )
    sep = "-" * len(col)

    def _pct(x, sign=True):
        if x is None:
            return "n/a"
        fmt = "+.2f" if sign else ".2f"
        return f"{x * 100:{fmt}}%"

    def _pf(pf):
        if pf is None:
            return "n/a"
        if pf == float("inf"):
            return "inf"
        return f"{pf:.2f}"

    rows = [
        f"{'Trades':<22} {agg['trades']:>14}",
        f"{'Win rate':<22} {_pct(agg['win_rate'], sign=False):>14}",
        f"{'Total return':<22} {_pct(agg['total_return']):>14}",
        f"{'Max drawdown':<22} {_pct(agg['max_drawdown']):>14}",
        f"{'Final equity':<22} {'$' + format(agg['final_equity'], ',.2f'):>14}",
        f"{'Profit factor':<22} {_pf(agg['profit_factor']):>14}",
        f"{'Expectancy / trade':<22} {_fmt_pct(agg['expectancy_pct']).strip():>14}",
        f"{'Avg winner':<22} {_fmt_pct(agg['avg_winner_pct']).strip():>14}",
        f"{'Avg loser':<22} {_fmt_pct(agg['avg_loser_pct']).strip():>14}",
        f"{'Winner : Loser':<22} {_fmt_ratio(agg['winner_loser_ratio']).strip():>14}",
    ]

    # Per-trade log (truncate to keep terminal output readable)
    trade_lines = ["", f"Trade log ({len(result['trades'])} trades, showing up to {max_trade_rows}):"]
    trade_hdr = f"{'Exit':<11} {'Ticker':<6} {'Shares':>6} {'Entry':>10} {'Exit':>10} {'Ret%':>7} {'PnL $':>10} {'Reason':<10}"
    trade_lines.append(trade_hdr)
    trade_lines.append("-" * len(trade_hdr))
    for t in result["trades"][:max_trade_rows]:
        trade_lines.append(
            f"{t['date']:<11} {t['ticker']:<6} {t['shares']:>6} "
            f"{t['entry_price']:>10.2f} {t['exit_price']:>10.2f} "
            f"{t['return_pct'] * 100:>+6.2f}% {t['pnl_dollars']:>+10.2f} {t['exit_reason']:<10}"
        )
    if len(result["trades"]) > max_trade_rows:
        trade_lines.append(f"... (+{len(result['trades']) - max_trade_rows} more)")

    # Rejected-signal summary
    rej_lines = ["", f"Rejected signals ({len(result['rejected'])} total):"]
    counts = {}
    for r in result["rejected"]:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    for reason, count in sorted(counts.items()):
        rej_lines.append(f"  {reason:<15} {count}")
    rej_lines.append("")
    rej_lines.append(f"Most recent rejections (up to {max_rejection_rows}):")
    rej_hdr = f"{'Date':<11} {'Ticker':<6} {'Reason':<15} {'Score':>7}"
    rej_lines.append(rej_hdr)
    rej_lines.append("-" * len(rej_hdr))
    for r in result["rejected"][-max_rejection_rows:]:
        rej_lines.append(f"{r['date']:<11} {r['ticker']:<6} {r['reason']:<15} {r['score']:>7.3f}")

    parts = [header, note, "", col, sep] + rows + trade_lines + rej_lines
    return "\n".join(parts)
