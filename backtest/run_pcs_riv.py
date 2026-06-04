"""Run the PCS-RIV backtest and print metrics vs SPY buy-and-hold.

Phase 1 Task 5 (issue #220). Two arms:
- modeled  — Black-Scholes option prices from SPY + VIX (yfinance), long history.
- real     — Alpaca historical trade marks (~2024-01 -> now); needs ALPACA keys.

The kill criterion: if the strategy's risk-adjusted return doesn't clear SPY
buy-and-hold after the (conservative, modeled) spread, the gate says KILL.

Usage:
    venv/bin/python -m backtest.run_pcs_riv --start 2015
    venv/bin/python -m backtest.run_pcs_riv --start 2024 --real
"""
from __future__ import annotations

import argparse
from datetime import date

import yfinance as yf

from backtest.options_data import ModeledSource, RealAlpacaSource
from backtest.pcs_riv import run_pcs_riv_backtest


def _fetch_close(ticker: str, start: str, end: str) -> dict:
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"no data for {ticker} {start}..{end}")
    close = df["Close"]
    if hasattr(close, "columns"):  # MultiIndex single-ticker frame
        close = close.iloc[:, 0]
    return {ts.date(): float(v) for ts, v in close.items()}


def _buy_and_hold(prices: dict, dates: list, starting_cash: float) -> dict:
    p0, p1 = prices[dates[0]], prices[dates[-1]]
    total_return = p1 / p0 - 1.0
    n_years = (dates[-1] - dates[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    series = [prices[d] for d in dates]
    peak, max_dd = series[0], 0.0
    for x in series:
        peak = max(peak, x)
        max_dd = min(max_dd, x / peak - 1.0)
    rets = [series[i] / series[i - 1] - 1.0 for i in range(1, len(series))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sharpe = (mean / var ** 0.5 * (252 ** 0.5)) if var > 0 else 0.0
    return {
        "total_return": total_return, "cagr": cagr, "max_drawdown": max_dd,
        "sharpe": sharpe, "ending_equity": starting_cash * (1 + total_return),
    }


def _row(name: str, m: dict) -> str:
    return (
        f"{name:<22} {m['total_return']*100:>9.1f}% {m['cagr']*100:>8.1f}% "
        f"{m['max_drawdown']*100:>9.1f}% {m['sharpe']:>7.2f} "
        f"{m.get('trade_count', '-'):>7} {m.get('win_rate', 0)*100 if 'win_rate' in m else 0:>7.0f}%"
    )


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_pcs_riv")
    parser.add_argument("--start", default="2015", help="start year")
    parser.add_argument("--underlying", default="SPY")
    parser.add_argument("--real", action="store_true", help="use Alpaca real marks (needs keys)")
    parser.add_argument("--iv-rank", type=float, default=30.0)
    parser.add_argument("--short-delta", type=float, default=0.30)
    parser.add_argument("--width", type=float, default=5.0)
    parser.add_argument("--sweep", action="store_true", help="grid over width x delta x IV-rank")
    parser.add_argument("--ablate", action="store_true", help="best config across regime gate on/off/inverted")
    args = parser.parse_args(argv)

    start, end = f"{args.start}-01-01", date.today().isoformat()
    print(f"Fetching {args.underlying} + ^VIX  {start} -> {end} ...")
    prices = _fetch_close(args.underlying, start, end)
    vix = _fetch_close("^VIX", start, end)
    dates = sorted(set(prices) & set(vix))
    prices = {d: prices[d] for d in dates}
    ivs = {d: vix[d] / 100.0 for d in dates}  # VIX % -> IV fraction (ATM proxy)

    starting_cash = 100_000.0

    if args.sweep:
        source = ModeledSource(prices, ivs, spread_frac=0.05)
        bh = _buy_and_hold(prices, dates, starting_cash)
        print(f"\nSweep (modeled arm)  {dates[0]} -> {dates[-1]}  ({(dates[-1]-dates[0]).days/365.25:.1f}y)")
        print(f"SPY buy-and-hold: total {bh['total_return']*100:.0f}%  sharpe {bh['sharpe']:.2f}\n")
        print(f"{'width':>6} {'delta':>6} {'ivR':>5} {'total':>9} {'cagr':>7} {'sharpe':>7} {'trades':>7} {'win':>6} {'pf':>6}")
        print("-" * 70)
        rows = []
        for width in (5.0, 10.0, 25.0):
            for delta in (0.20, 0.30):
                for ivr in (30.0, 50.0):
                    r = run_pcs_riv_backtest(
                        source=source, underlyings=[args.underlying], spy_closes=prices,
                        iv_series=vix, trading_dates=dates, iv_rank_threshold=ivr,
                        short_delta=delta, width=width, starting_cash=starting_cash,
                    )
                    rows.append((width, delta, ivr, r))
        for width, delta, ivr, r in sorted(rows, key=lambda x: x[3]["sharpe"], reverse=True):
            pf = r["profit_factor"]
            print(f"{width:>6.0f} {delta:>6.2f} {ivr:>5.0f} {r['total_return']*100:>8.1f}% "
                  f"{r['cagr']*100:>6.1f}% {r['sharpe']:>7.2f} {r['trade_count']:>7} "
                  f"{r['win_rate']*100:>5.0f}% {pf:>6.2f}")
        best = max(rows, key=lambda x: x[3]["sharpe"])[3]
        verdict = "GO" if best["sharpe"] > bh["sharpe"] and best["total_return"] > 0 else "KILL"
        print(f"\nBest-case Sharpe {best['sharpe']:.2f} vs SPY {bh['sharpe']:.2f}  ->  {verdict}")
        return 0

    if args.ablate:
        source = ModeledSource(prices, ivs, spread_frac=0.05)
        bh = _buy_and_hold(prices, dates, starting_cash)
        print(f"\nRegime-gate ablation (modeled arm)  {dates[0]} -> {dates[-1]}  ({(dates[-1]-dates[0]).days/365.25:.1f}y)")
        print(f"Config: width 25, delta 0.30, IV-rank>=30   |   SPY buy-hold: total {bh['total_return']*100:.0f}%  sharpe {bh['sharpe']:.2f}\n")
        print(f"{'regime_mode':<14} {'total':>9} {'cagr':>7} {'sharpe':>7} {'trades':>7} {'win':>6} {'pf':>6}")
        print("-" * 60)
        for mode in ("bullish", "any", "bearish"):
            r = run_pcs_riv_backtest(
                source=source, underlyings=[args.underlying], spy_closes=prices, iv_series=vix,
                trading_dates=dates, iv_rank_threshold=30.0, short_delta=0.30, width=25.0,
                starting_cash=starting_cash, regime_mode=mode,
            )
            print(f"{mode:<14} {r['total_return']*100:>8.1f}% {r['cagr']*100:>6.1f}% {r['sharpe']:>7.2f} "
                  f"{r['trade_count']:>7} {r['win_rate']*100:>5.0f}% {r['profit_factor']:>6.2f}")
        return 0

    common = dict(
        underlyings=[args.underlying], spy_closes=prices, iv_series=vix,
        trading_dates=dates, iv_rank_threshold=args.iv_rank,
        short_delta=args.short_delta, width=args.width, starting_cash=starting_cash,
    )

    if args.real:
        source = RealAlpacaSource(spread_frac=0.05)
        arm = "real (Alpaca marks)"
    else:
        source = ModeledSource(prices, ivs, spread_frac=0.05)
        arm = "modeled (BS from VIX)"

    try:
        res = run_pcs_riv_backtest(source=source, **common)
    except NotImplementedError:
        print(
            "\nThe --real arm needs RealAlpacaSource._fetch_put_chain_marks (the live\n"
            "multi-contract chain crawl), which is a follow-up. The modeled-arm sweep\n"
            "(`--sweep`) is the Phase 1 verdict; real data over ~2.4y would only confirm it."
        )
        return 0
    bh = _buy_and_hold(prices, dates, starting_cash)

    print(f"\nPCS-RIV backtest — arm: {arm}")
    print(f"Window: {dates[0]} -> {dates[-1]}  ({(dates[-1]-dates[0]).days/365.25:.1f}y, {len(dates)} days)")
    print(f"Params: short_delta={args.short_delta}  width={args.width}  IV-rank>={args.iv_rank}\n")
    print(f"{'strategy':<22} {'total':>10} {'cagr':>9} {'maxDD':>10} {'sharpe':>7} {'trades':>7} {'win':>8}")
    print("-" * 80)
    print(_row("PCS-RIV", res))
    print(_row("SPY buy-and-hold", bh))
    print()
    verdict = "GO (clears buy-hold)" if res["sharpe"] > bh["sharpe"] and res["total_return"] > 0 else "KILL (does not clear buy-hold)"
    print(f"Profit factor: {res['profit_factor']:.2f}   Ending equity: ${res['ending_equity']:,.0f}")
    print(f"Gate (Sharpe vs SPY buy-hold): {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
