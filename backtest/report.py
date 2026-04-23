from __future__ import annotations

from tools.notifications import notify_backtest


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
    col = f"{'Ticker':<8} {'Trades':>6} {'Win%':>6} {'Return':>9} {'Max DD':>8}"
    sep = "-" * len(col)

    rows = [
        f"{ticker:<8} {s['trades']:>6} "
        f"{s['win_rate'] * 100:>5.1f}% "
        f"{s['total_return'] * 100:>+8.1f}% "
        f"{s['max_drawdown'] * 100:>7.1f}%"
        for ticker, s in result["tickers"].items()
    ]
    total = (
        f"{'TOTAL':<8} {agg['trades']:>6} "
        f"{agg['win_rate'] * 100:>5.1f}% "
        f"{agg['total_return'] * 100:>+8.1f}% "
        f"{agg['max_drawdown'] * 100:>7.1f}%"
    )
    return "\n".join([header, note, "", col, sep] + rows + [sep, total])
