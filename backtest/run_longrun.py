"""Driver for the long-horizon regime-vs-SPY research note (research only).

Produces the four windows in docs/research/2026-06-06-regime-vs-spy-longrun-backtest.md:
  W1  10y real (2016-2026)
  W2  full real UPRO life (2009-06 -> now) + risk dials (SSO 2x, UPRO @50%)
  W3  synthetic 1990 -> now (synth 3x/2x B&H + bot variants)
  W4  crash-stress drawdowns within W3

Run:  PYTHONPATH=. venv/bin/python backtest/run_longrun.py
All numbers come from actual yfinance downloads at run time.
"""
from __future__ import annotations

import warnings
from datetime import date

import pandas as pd

warnings.filterwarnings("ignore")

from backtest.regime import run_regime_backtest  # noqa: E402
from backtest.synthetic import (  # noqa: E402
    SSO_EXPENSE,
    UPRO_EXPENSE,
    build_synthetic_leverage,
    buy_and_hold,
    daily_risk_free,
    drawdown_in_window,
    fetch_close,
    fetch_ohlc,
    run_synthetic_regime,
    validate_synthetic,
)

END = date(2026, 6, 6)


def pct(x: float) -> str:
    return f"{x*100:+.1f}%"


def fmt_row(name: str, r: dict, trades=None) -> str:
    t = "" if trades is None else f"  trades={trades}"
    return (
        f"  {name:34s} total={pct(r['total_return']):>9s}  "
        f"cagr={r['cagr']*100:5.1f}%  maxDD={r['max_drawdown']*100:6.1f}%{t}"
    )


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    # ---- shared data ----
    section("DATA LOAD")
    start_all = date(1988, 1, 1)
    sp500tr = fetch_close("^SP500TR", start_all, END)
    gspc = fetch_close("^GSPC", start_all, END)
    irx = fetch_close("^IRX", start_all, END)
    rf = daily_risk_free(start_all, END, irx=irx)
    print(f"^SP500TR : {sp500tr.index[0].date()} -> {sp500tr.index[-1].date()}  ({len(sp500tr)} days)")
    print(f"^GSPC    : {gspc.index[0].date()} -> {gspc.index[-1].date()}  ({len(gspc)} days)")
    print(f"^IRX     : {irx.index[0].date()} -> {irx.index[-1].date()}  ({len(irx)} days)")

    # Full-history synthetic vehicles (built once, sliced per window)
    synth3_full = build_synthetic_leverage(sp500tr, leverage=3, annual_expense=UPRO_EXPENSE, rf_daily=rf)
    synth2_full = build_synthetic_leverage(sp500tr, leverage=2, annual_expense=SSO_EXPENSE, rf_daily=rf)

    # ---- VALIDATION ----
    section("VALIDATION  (synthetic vs real, gate for pre-2009/2006 numbers)")
    upro_close = fetch_close("UPRO", date(2009, 6, 1), END)
    sso_close = fetch_close("SSO", date(2006, 6, 1), END)
    v3 = validate_synthetic(synth3_full["Close"], upro_close, "synthetic-3x vs real UPRO")
    v2 = validate_synthetic(synth2_full["Close"], sso_close, "synthetic-2x vs real SSO")
    for v in (v3, v2):
        print(f"\n{v['label']}  [{v['overlap_start']} -> {v['overlap_end']}, {v['n_days']} days]")
        print(f"  daily-return correlation : {v['daily_return_corr']:.4f}")
        print(f"  total return  synth={pct(v['synth_total_return']/1):>10s}  real={pct(v['real_total_return']):>10s}  gap={v['total_return_gap_pp']:+.1f} pp")
        print(f"  CAGR          synth={v['synth_cagr']*100:6.2f}%  real={v['real_cagr']*100:6.2f}%  gap={v['cagr_gap_pp']:+.2f} pp")

    # ---- W1: 10y real ----
    section("W1  10y REAL  (2016-06-06 -> 2026-06-06)")
    w1s = date(2016, 6, 6)
    spy_w1 = fetch_ohlc("SPY", w1s, END)
    upro_w1 = fetch_ohlc("UPRO", w1s, END)
    print(fmt_row("SPY B&H", buy_and_hold(spy_w1)))
    print(fmt_row("UPRO B&H (3x, no timing)", buy_and_hold(upro_w1)))
    bot_w1 = run_regime_backtest(benchmark_ticker="SPY", vehicle_ticker="UPRO", start=w1s, end=END)
    print(fmt_row("bot UPRO+200DMA @100%", bot_w1, bot_w1["trade_count"]))

    # ---- W2: full real UPRO life ----
    section("W2  FULL REAL UPRO LIFE  (2009-06-25 -> 2026-06-06)")
    w2s = date(2009, 6, 25)
    spy_w2 = fetch_ohlc("SPY", w2s, END)
    upro_w2 = fetch_ohlc("UPRO", w2s, END)
    sso_w2 = fetch_ohlc("SSO", w2s, END)
    print(fmt_row("SPY B&H", buy_and_hold(spy_w2)))
    print(fmt_row("UPRO B&H (3x, no timing)", buy_and_hold(upro_w2)))
    print(fmt_row("SSO B&H (2x, no timing)", buy_and_hold(sso_w2)))
    bot_w2_upro = run_regime_backtest(benchmark_ticker="SPY", vehicle_ticker="UPRO", start=w2s, end=END)
    print(fmt_row("bot UPRO+200DMA @100%", bot_w2_upro, bot_w2_upro["trade_count"]))
    bot_w2_sso = run_regime_backtest(benchmark_ticker="SPY", vehicle_ticker="SSO", start=w2s, end=END)
    print(fmt_row("bot SSO(2x)+200DMA @100%", bot_w2_sso, bot_w2_sso["trade_count"]))
    bot_w2_upro50 = run_regime_backtest(benchmark_ticker="SPY", vehicle_ticker="UPRO", start=w2s, end=END, alloc_frac=0.5)
    print(fmt_row("bot UPRO+200DMA @50%", bot_w2_upro50, bot_w2_upro50["trade_count"]))

    # ---- W3: synthetic 1990 -> now ----
    section("W3  SYNTHETIC  (1990-01-01 -> 2026-06-06)  [pre-2009 3x / pre-2006 2x = SYNTHETIC]")
    w3s = date(1990, 1, 1)
    idx_w3 = sp500tr.loc[str(w3s):]          # index TR for B&H of the index
    gspc_w3 = gspc.loc[str(w3s):]            # price index = 200-DMA signal source
    synth3_w3 = synth3_full.loc[str(w3s):]
    synth2_w3 = synth2_full.loc[str(w3s):]
    idx_ohlc = pd.DataFrame({"Open": idx_w3, "Close": idx_w3})
    print(fmt_row("S&P 500 TR index B&H", buy_and_hold(idx_ohlc)))
    print(fmt_row("synthetic-UPRO(3x) B&H", buy_and_hold(synth3_w3)))
    print(fmt_row("synthetic-SSO(2x) B&H", buy_and_hold(synth2_w3)))
    bot3 = run_synthetic_regime(gspc_w3, synth3_w3, start=w3s, end=END)
    print(fmt_row("bot on synth-3x @100%", bot3, bot3["trade_count"]))
    bot3_50 = run_synthetic_regime(gspc_w3, synth3_w3, start=w3s, end=END, alloc_frac=0.5)
    print(fmt_row("bot on synth-3x @50%", bot3_50, bot3_50["trade_count"]))
    bot2 = run_synthetic_regime(gspc_w3, synth2_w3, start=w3s, end=END)
    print(fmt_row("bot on synth-2x @100%", bot2, bot2["trade_count"]))

    # ---- W4: crash stress ----
    section("W4  CRASH STRESS  (peak-to-trough drawdown within each bear, W3 synthetic)")
    spy_bh_eq = buy_and_hold(idx_ohlc)["equity_curve"]
    synth3_bh_eq = buy_and_hold(synth3_w3)["equity_curve"]
    bot3_eq = bot3["equity_curve"]
    crashes = {
        "Dot-com (2000-09 -> 2002-10)": ("2000-09-01", "2002-10-31"),
        "GFC (2007-10 -> 2009-03)": ("2007-10-01", "2009-03-31"),
        "COVID (2020-02 -> 2020-04)": ("2020-02-15", "2020-04-30"),
        "2022 bear (2022-01 -> 2022-10)": ("2022-01-01", "2022-10-31"),
    }
    print(f"  {'crash':32s} {'SPY(idx)':>10s} {'synth-3x B&H':>13s} {'bot synth-3x':>13s}")
    for name, (s, e) in crashes.items():
        d_spy = drawdown_in_window(spy_bh_eq, s, e)
        d_s3 = drawdown_in_window(synth3_bh_eq, s, e)
        d_bot = drawdown_in_window(bot3_eq, s, e)
        print(f"  {name:32s} {d_spy*100:9.1f}% {d_s3*100:12.1f}% {d_bot*100:12.1f}%")


if __name__ == "__main__":
    main()
