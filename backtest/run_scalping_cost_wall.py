"""Cost-wall demonstration: the YouTube video's scalping strategy on real BTC.

Research-only (issue #311). Makes #309's cost arithmetic empirical: run a faithful
reconstruction of the "ATR trend multi-confirmation" scalper on REAL BTC intraday
OHLCV, twice (costs off vs on), and show where transaction cost flips it from win to
loss. Imports no Alpaca client, places no orders, hits only Bybit's PUBLIC read-only
market-data REST (no auth, no order capability) -- does not touch the broker guard.

The load-bearing finding is the costs-off-vs-on DELTA and the BREAK-EVEN cost, not the
absolute P/L of a strategy whose exact Pine params are unknown.

Run:  python3 backtest/run_scalping_cost_wall.py
All numbers come from a live Bybit pull at run time; no price is ever fabricated.
If no data source works the script raises SystemExit("BLOCKED: ...") rather than
inventing prices.

Data        : Bybit v5 public linear perp klines, BTCUSDT
Window      : pinned UTC literals below (WINDOW_START / WINDOW_END)
Strategy    : long/short supertrend(ATR10, mult3.0, hand-rolled) AND ADX(14)>25 AND
              volume>SMA(volume,20) AND MACD-hist(12/26/9) agrees; ATR stop at
              entry -/+ 2*ATR; ATR trailing-stop take-profit (ratchets on prior bars).
No look-ahead: signal on bar t (close) -> fill at bar t+1 open; stop/TP checked only
              against subsequent bars; both-touched bar -> stop-first (conservative);
              trailing stop ratchets on bars strictly before the bar being tested;
              in-progress last bar dropped.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

warnings.filterwarnings("ignore")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from ta.trend import ADXIndicator, MACD
from ta.volatility import AverageTrueRange

# --- Pinned reproducibility window (UTC literals) ---------------------------------
WINDOW_START = datetime(2025, 6, 23, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)

BYBIT_KLINE = "https://api.bybit.com/v5/market/kline"
SYMBOL = "BTCUSDT"

# --- Strategy params (standard defaults; exact Pine params unknown) ---------------
ATR_LEN = 10
ST_MULT = 3.0
ADX_LEN = 14
ADX_MIN = 25.0
VOL_SMA = 20
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
STOP_ATR_MULT = 2.0  # initial stop = entry -/+ 2*ATR
TRAIL_ATR_MULT = 2.0  # trailing-stop take-profit ratchet distance

STARTING_EQUITY = 100_000.0

# Realistic round-trip cost on Bybit perp (taker), as a FRACTION of notional.
# Bybit taker fee 0.055%/side (https://www.bybit.com/en/help-center/article/Trading-Fee-Structure
# fetched 2026-06-23) = 0.11% round-trip in fees. Add a stated crossed-spread
# assumption ~1 bp/side for BTC perp top-of-book = ~0.02% round-trip. Funding ~0 for
# short scalps (only ever adds cost). Realistic round-trip ~= 0.13%.
BYBIT_TAKER_RT = 0.0011  # 0.11% fees round trip
SPREAD_RT = 0.0002  # 0.02% crossed-spread round trip
REALISTIC_RT = BYBIT_TAKER_RT + SPREAD_RT  # ~0.13% round trip

# Alpaca crypto taker fee for the 309 reconciliation marker (0.25%/side -> 0.50% RT).
ALPACA_TAKER_RT = 0.0050

# Cost sweep (round-trip fraction of notional): 0 -> 0.8%.
COST_SWEEP = [0.0, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.008]


# ---------------------------------------------------------------------------------
# 1. DATA: real BTC intraday OHLCV from Bybit v5 public klines.
# ---------------------------------------------------------------------------------
def fetch_bybit(interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Paginate Bybit v5 linear klines over [start, end). Newest-first per page;
    we walk backwards via the `end` cursor, then sort chronological and dedupe.

    interval: Bybit string, e.g. '60' (1h), '15', '5' (minutes).
    Returns OHLCV DataFrame indexed by UTC open-time. Raises on empty.
    """
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[list[str]] = []
    cursor = end_ms
    while cursor > start_ms:
        params = {
            "category": "linear",
            "symbol": SYMBOL,
            "interval": interval,
            "start": start_ms,
            "end": cursor,
            "limit": 1000,
        }
        resp = requests.get(BYBIT_KLINE, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit retCode {payload.get('retCode')}: {payload.get('retMsg')}")
        page = payload["result"]["list"]
        if not page:
            break
        rows.extend(page)
        # page is newest-first; oldest open-time on this page sets the next cursor.
        oldest = min(int(r[0]) for r in page)
        if oldest <= start_ms:
            break
        cursor = oldest  # exclusive upper bound next loop -> no overlap dupes kept
        time.sleep(0.1)  # be polite to the public endpoint

    if not rows:
        raise RuntimeError("Bybit returned no rows")

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    df["ts"] = df["ts"].astype("int64")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df = df.drop_duplicates(subset="ts").sort_values("ts")
    # Keep only bars whose OPEN time is within [start, end).
    df = df[(df["ts"] >= start_ms) & (df["ts"] < end_ms)]
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]]


def load_data(interval: str) -> pd.DataFrame:
    """Fetch real OHLCV; drop the in-progress final bar. BLOCKED if nothing works."""
    try:
        df = fetch_bybit(interval, WINDOW_START, WINDOW_END)
    except Exception as exc:  # noqa: BLE001 -- surface any source failure as BLOCKED
        raise SystemExit(
            f"BLOCKED: Bybit fetch failed for interval={interval} ({exc}). "
            "Refusing to fabricate prices. Document the failure and a fallback "
            "(Coinbase / yfinance) before proceeding."
        )
    # Drop the in-progress bar if the last bar's window has not fully elapsed.
    # Our window end is pinned in the past, so this is belt-and-suspenders.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = int(interval) * 60_000
    last_open_ms = int(df.index[-1].value // 1_000_000)
    if last_open_ms + interval_ms > now_ms:
        df = df.iloc[:-1]
    return df


# ---------------------------------------------------------------------------------
# 2. INDICATORS: hand-rolled supertrend + ta ADX/MACD/ATR.
# ---------------------------------------------------------------------------------
def supertrend(df: pd.DataFrame, atr: pd.Series, mult: float) -> pd.Series:
    """Hand-rolled supertrend direction. Returns +1 (uptrend) / -1 (downtrend),
    using only information up to and including the current bar's close.
    Standard band construction with the carry-forward locking rule.
    """
    hl2 = (df["high"] + df["low"]) / 2.0
    upper = (hl2 + mult * atr).values
    lower = (hl2 - mult * atr).values
    close = df["close"].values
    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)  # +1 up, -1 down

    for i in range(n):
        if i == 0 or np.isnan(atr.iloc[i]):
            final_upper[i] = upper[i]
            final_lower[i] = lower[i]
            direction[i] = 1
            continue
        # Lock bands: upper only ratchets down, lower only ratchets up,
        # until price closes through them.
        final_upper[i] = (
            min(upper[i], final_upper[i - 1]) if close[i - 1] <= final_upper[i - 1] else upper[i]
        )
        final_lower[i] = (
            max(lower[i], final_lower[i - 1]) if close[i - 1] >= final_lower[i - 1] else lower[i]
        )
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Attach indicator columns and the long/short entry signal (on bar t close)."""
    out = df.copy()
    atr = AverageTrueRange(out["high"], out["low"], out["close"], window=ATR_LEN).average_true_range()
    out["atr"] = atr
    out["st_dir"] = supertrend(out, atr, ST_MULT)
    out["adx"] = ADXIndicator(out["high"], out["low"], out["close"], window=ADX_LEN).adx()
    macd = MACD(out["close"], window_slow=MACD_SLOW, window_fast=MACD_FAST, window_sign=MACD_SIG)
    out["macd_hist"] = macd.macd_diff()
    out["vol_sma"] = out["volume"].rolling(VOL_SMA).mean()

    trend_ok = out["adx"] > ADX_MIN
    vol_ok = out["volume"] > out["vol_sma"]
    long_sig = (out["st_dir"] == 1) & trend_ok & vol_ok & (out["macd_hist"] > 0)
    short_sig = (out["st_dir"] == -1) & trend_ok & vol_ok & (out["macd_hist"] < 0)
    # entry_dir on bar t: +1 long, -1 short, 0 flat. NaN indicator rows -> flat.
    out["entry_dir"] = 0
    out.loc[long_sig.fillna(False), "entry_dir"] = 1
    out.loc[short_sig.fillna(False), "entry_dir"] = -1
    return out


# ---------------------------------------------------------------------------------
# 3. BAR LOOP: no look-ahead, intra-bar stop/trailing-TP, costs on every fill.
# ---------------------------------------------------------------------------------
@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    direction: int  # +1 long, -1 short
    entry_price: float
    exit_price: float
    gross_return: float  # signed, on notional, before cost
    net_return: float  # after round-trip cost
    exit_reason: str  # "stop" | "trail" | "end_of_window"


def run_backtest(sig: pd.DataFrame, cost_rt: float) -> dict:
    """Single-position long/short bar loop.

    cost_rt: round-trip cost as a fraction of notional, charged once per round trip.
    Look-ahead controls:
      - signal read from bar t close; entry executed at bar t+1 open.
      - while in a trade, the trailing stop ratchets using extremes of bars STRICTLY
        BEFORE the bar being tested; the current bar's high/low only trigger exits.
      - a bar that touches the stop -> exit at the stop level (stop-first, no
        gap-through gift).
    """
    opens = sig["open"].values
    highs = sig["high"].values
    lows = sig["low"].values
    closes = sig["close"].values
    atrs = sig["atr"].values
    entry_dir = sig["entry_dir"].values
    idx = sig.index
    n = len(sig)

    trades: list[Trade] = []
    in_pos = False
    direction = 0
    entry_price = 0.0
    entry_ts: Optional[pd.Timestamp] = None
    entry_atr = 0.0
    initial_stop = 0.0
    trail_stop = 0.0  # ratcheted level, updated from prior bars only

    equity = STARTING_EQUITY
    eq_curve: list[tuple] = []

    i = 0
    while i < n:
        ts = idx[i]
        if not in_pos:
            # Decide entry from the PREVIOUS bar's signal (t-1 close -> t open).
            prev_dir = int(entry_dir[i - 1]) if i >= 1 else 0
            if prev_dir != 0 and not np.isnan(atrs[i - 1]):
                in_pos = True
                direction = prev_dir
                entry_price = opens[i]
                entry_ts = ts
                entry_atr = atrs[i - 1]
                if direction == 1:
                    initial_stop = entry_price - STOP_ATR_MULT * entry_atr
                    trail_stop = entry_price - TRAIL_ATR_MULT * entry_atr
                else:
                    initial_stop = entry_price + STOP_ATR_MULT * entry_atr
                    trail_stop = entry_price + TRAIL_ATR_MULT * entry_atr
            eq_curve.append((ts, equity))
            i += 1
            continue

        # In a position. The trailing stop was ratcheted on bars BEFORE i (at the end
        # of the previous iteration). Test THIS bar's high/low against the binding
        # stop (max of initial and trail for longs; min for shorts).
        if direction == 1:
            stop_level = max(initial_stop, trail_stop)
            hit_stop = lows[i] <= stop_level
        else:
            stop_level = min(initial_stop, trail_stop)
            hit_stop = highs[i] >= stop_level

        if hit_stop:
            exit_price = stop_level  # conservative: fill at the stop, no gap-through gift
            gross = direction * (exit_price / entry_price - 1.0)
            net = gross - cost_rt
            trailing_binding = (
                (direction == 1 and trail_stop > initial_stop)
                or (direction == -1 and trail_stop < initial_stop)
            )
            reason = "trail" if trailing_binding else "stop"
            trades.append(
                Trade(entry_ts, ts, direction, entry_price, exit_price, gross, net, reason)
            )
            equity *= (1.0 + net)
            eq_curve.append((ts, equity))
            in_pos = False
            i += 1
            continue

        # No exit this bar: mark equity to THIS bar's close (unrealized, signed) so
        # max DD reflects intra-trade drawdown, not just closed trades. Entry cost is
        # already booked at exit, so subtract the entry half here for a fair mark.
        unreal = direction * (closes[i] / entry_price - 1.0) - cost_rt / 2.0
        eq_curve.append((ts, equity * (1.0 + unreal)))

        # Ratchet the trailing stop using THIS bar's extreme so it is in force for
        # the NEXT bar (never used to test the current bar).
        if direction == 1:
            trail_stop = max(trail_stop, highs[i] - TRAIL_ATR_MULT * entry_atr)
        else:
            trail_stop = min(trail_stop, lows[i] + TRAIL_ATR_MULT * entry_atr)
        i += 1

    # Close any open position at the final bar's close.
    if in_pos:
        ts = idx[-1]
        exit_price = closes[-1]
        gross = direction * (exit_price / entry_price - 1.0)
        net = gross - cost_rt
        trades.append(
            Trade(entry_ts, ts, direction, entry_price, exit_price, gross, net, "end_of_window")
        )
        equity *= (1.0 + net)
        eq_curve[-1] = (eq_curve[-1][0], equity)

    eq = pd.Series(dict(eq_curve))
    total_return = float(eq.iloc[-1] / STARTING_EQUITY - 1.0)
    roll_max = eq.cummax()
    max_dd = float(((eq - roll_max) / roll_max).min()) if len(eq) else 0.0

    nets = np.array([t.net_return for t in trades])
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    win_rate = float(len(wins) / len(trades)) if trades else 0.0
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # No-look-ahead self-check: every exit strictly after its entry.
    for t in trades:
        assert t.exit_ts > t.entry_ts, f"exit {t.exit_ts} not after entry {t.entry_ts}"

    return {
        "cost_rt": cost_rt,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "equity_curve": eq,
        "trades": trades,
    }


# ---------------------------------------------------------------------------------
# 4. REPORTING
# ---------------------------------------------------------------------------------
def pf_str(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_regime_table(rows: list[dict], title: str) -> None:
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)
    print(f"{'cost RT':>9} | {'net return':>11} | {'max DD':>8} | {'PF':>6} | {'#trades':>7} | {'win rate':>8}")
    print("-" * 92)
    for r in rows:
        print(
            f"{r['cost_rt']*100:8.3f}% | {r['total_return']*100:+10.2f}% | "
            f"{r['max_drawdown']*100:7.1f}% | {pf_str(r['profit_factor']):>6} | "
            f"{r['trade_count']:7d} | {r['win_rate']*100:7.1f}%"
        )


def break_even_cost(sweep_rows: list[dict]) -> Optional[float]:
    """Linear-interpolate the round-trip cost where net return crosses zero."""
    if sweep_rows and sweep_rows[0]["total_return"] <= 0:
        return 0.0  # already a loss at zero cost
    prev = None
    for r in sweep_rows:
        if prev is not None and prev["total_return"] > 0 >= r["total_return"]:
            x0, y0 = prev["cost_rt"], prev["total_return"]
            x1, y1 = r["cost_rt"], r["total_return"]
            return x0 + (0 - y0) * (x1 - x0) / (y1 - y0)
        prev = r
    return None  # stays positive across the whole sweep


def make_chart(off: dict, on: dict, path: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(off["equity_curve"].index, off["equity_curve"].values,
            label=f"costs OFF (net {off['total_return']*100:+.1f}%)", lw=1.4)
    ax.plot(on["equity_curve"].index, on["equity_curve"].values,
            label=f"costs ON {on['cost_rt']*100:.2f}% RT (net {on['total_return']*100:+.1f}%)",
            lw=1.4, color="crimson")
    ax.axhline(STARTING_EQUITY, color="grey", lw=0.8, ls="--")
    ax.set_title("Scalping strategy on BTCUSDT 1h -- equity, costs off vs on\n"
                 f"{WINDOW_START.date()} to {WINDOW_END.date()} (Bybit perp, real data)")
    ax.set_ylabel("equity ($)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"\nChart written: {path}")


# ---------------------------------------------------------------------------------
def main() -> None:
    print("Cost-wall demonstration (#311) -- scalping strategy on real BTC intraday")
    print(f"Window: {WINDOW_START.isoformat()} -> {WINDOW_END.isoformat()} (UTC)")
    print(f"Realistic round-trip cost (Bybit perp taker+spread): {REALISTIC_RT*100:.3f}%")

    # --- 1h spine ---
    print("\nFetching 1h klines from Bybit ...")
    df_1h = load_data("60")
    print(f"  Bybit linear BTCUSDT 1h: {len(df_1h)} bars, "
          f"{df_1h.index[0].isoformat()} -> {df_1h.index[-1].isoformat()}")
    sig_1h = build_signals(df_1h)

    # Cost sweep on the 1h spine.
    sweep = [run_backtest(sig_1h, c) for c in COST_SWEEP]
    print_regime_table(sweep, "1h COST SWEEP (same strategy + data; cost is the only varied input)")

    be = break_even_cost(sweep)
    if be is None:
        print("\nBreak-even round-trip cost: > 0.80% (net return stays positive across the sweep)")
    elif be == 0.0:
        print("\nBreak-even round-trip cost: 0.000% (already a loss at zero cost)")
    else:
        print(f"\nBreak-even round-trip cost: {be*100:.3f}% (net return crosses zero here)")
    print(f"  Realistic Bybit perp cost : {REALISTIC_RT*100:.3f}% round-trip")
    print(f"  Alpaca crypto taker cost  : {ALPACA_TAKER_RT*100:.3f}% round-trip (309 reconciliation marker)")

    # Headline two-regime rows.
    off = next(r for r in sweep if r["cost_rt"] == 0.0)
    on = run_backtest(sig_1h, REALISTIC_RT)
    alpaca = run_backtest(sig_1h, ALPACA_TAKER_RT)
    print_regime_table([off, on, alpaca],
                       "1h HEADLINE REGIMES: cost OFF vs realistic Bybit vs Alpaca-crypto fee")

    # --- frequency sweep at the realistic cost ---
    print("\nFetching sub-hour klines for the frequency sweep ...")
    freq_rows = []
    for label, interval in [("1h", "60"), ("15m", "15"), ("5m", "5")]:
        if interval == "60":
            sig = sig_1h
            nbars = len(df_1h)
        else:
            dfi = load_data(interval)
            print(f"  Bybit linear BTCUSDT {label}: {len(dfi)} bars")
            sig = build_signals(dfi)
            nbars = len(dfi)
        r = run_backtest(sig, REALISTIC_RT)
        r["label"] = label
        r["nbars"] = nbars
        freq_rows.append(r)

    print("\n" + "=" * 92)
    print(f"FREQUENCY SWEEP at realistic cost {REALISTIC_RT*100:.3f}% RT "
          "(same strategy + window; resolution is the only varied input)")
    print("=" * 92)
    print(f"{'tf':>4} | {'bars':>7} | {'net return':>11} | {'max DD':>8} | {'PF':>6} | {'#trades':>7} | {'win rate':>8}")
    print("-" * 92)
    for r in freq_rows:
        print(
            f"{r['label']:>4} | {r['nbars']:7d} | {r['total_return']*100:+10.2f}% | "
            f"{r['max_drawdown']*100:7.1f}% | {pf_str(r['profit_factor']):>6} | "
            f"{r['trade_count']:7d} | {r['win_rate']*100:7.1f}%"
        )

    # --- chart ---
    chart_path = "docs/research/2026-06-23-scalping-cost-wall-equity-curve.png"
    make_chart(off, on, chart_path)

    print("\nDone. All numbers above came from a live Bybit pull; no price was fabricated.")


if __name__ == "__main__":
    main()
