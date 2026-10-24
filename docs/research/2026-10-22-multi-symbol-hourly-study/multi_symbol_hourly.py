"""Multi-symbol replay of the live hourly candlestick rule (2026-10-22 study library).

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker call, no
network (inputs are local CSVs staged by ``fetch_yahoo_bars.py`` plus the #571 staged SPY
SIP bars). Signals/geometry/sizing validity come from the LIVE TypeScript exports via two
file-in/file-out emitters (``scripts/emit_hourly_decisions.ts`` for the top-of-hour grid,
``emit_proxy_decisions.ts`` for Yahoo's :30 grid); this module only owns the
state-dependent half of the gate ladder (one position per symbol, cooldown, day cap,
flatten scans) plus cost application and statistics -- the same split #571 used.

Exit resolution reuses ``backtest/bracket.py::_resolve_bar`` unchanged (open-gap first,
STOP-first on a both-touched bar). ``backtest/hourly_geometry.is_flatten_scan`` is reused
unchanged for the top-of-hour grid.

Simulation is cost-free at the price-path level (costs never change which bar a bracket
resolves on); per-side costs are applied afterwards in ``r_at_cost`` so every cost model
in the pre-registration (§5) is evaluated on the identical trade path.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backtest.bracket import LONG as BR_LONG, SHORT as BR_SHORT, _resolve_bar  # noqa: E402
from backtest.hourly_geometry import is_flatten_scan  # noqa: E402
from backtest.overfitting_gate import block_bootstrap_ci  # noqa: E402

SCAN_OFFSET_MIN = 7
DAY_CAP = 3
HOUR_MS = 3_600_000
NY = "America/New_York"

TOP10 = ("NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "AVGO", "META", "TSLA", "MU", "LLY")
ETFS = ("QQQ", "IWM", "DIA", "XLK", "XLF")
CONTROLS = ("BRK-B", "JPM", "UNH")
ALL_SYMBOLS = ("SPY",) + TOP10 + ETFS + CONTROLS


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def load_bars(path: "str | Path") -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    out = df[["Open", "High", "Low", "Close"]].astype(float).copy()
    if "Volume" in df.columns:
        out["Volume"] = df["Volume"].astype(float)
    out.index = pd.DatetimeIndex(ts)
    out.index.name = "timestamp"
    return out.sort_index()


def _write_bars(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    out.index = out.index.strftime("%Y-%m-%d %H:%M:%S+00:00")
    out.index.name = "timestamp"
    out.to_csv(path)


def _ny_dates(idx: pd.DatetimeIndex) -> np.ndarray:
    return idx.tz_convert(NY).strftime("%Y-%m-%d").to_numpy()


def rth_only(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bars starting in [09:30, 16:00) New York time."""
    local = df.index.tz_convert(NY)
    mins = local.hour * 60 + local.minute
    return df[(mins >= 570) & (mins < 960)]


def resample_top_of_hour(df5: pd.DataFrame) -> pd.DataFrame:
    """5Min RTH bars -> top-of-hour 60m bars (label = bar start, UTC), the grid live sees."""
    agg = df5.resample("60min", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    )
    return agg.dropna()


def resample_half_hour_grid(df5: pd.DataFrame) -> pd.DataFrame:
    """5Min RTH bars -> :30-aligned 60m bars per NY session (09:30, 10:30, ..., 15:30 stub).

    Builds Yahoo's 1h grid from SIP data so the proxy construction can be measured on the
    same feed as the reference harness (pre-registration §4.3, gate P0c).
    """
    local = df5.copy()
    local.index = local.index.tz_convert(NY)
    agg = local.resample("60min", label="left", closed="left", offset="30min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    ).dropna()
    agg.index = agg.index.tz_convert("UTC")
    return agg


def prepare_inputs(raw_dir: Path, out_dir: Path, end_date: str, symbols: Sequence[str]) -> None:
    """Round Yahoo floats to 4 dp, drop bars after ``end_date`` (NY), write harness inputs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        for kind in ("1h", "5m"):
            df = load_bars(raw_dir / f"{sym}_{kind}_yahoo.csv")
            df[["Open", "High", "Low", "Close"]] = df[["Open", "High", "Low", "Close"]].round(4)
            df = df[_ny_dates(df.index) <= end_date]
            df = rth_only(df)
            if kind == "1h":
                _write_bars(df, out_dir / f"{sym}_1h_proxy.csv")
            else:
                _write_bars(df, out_dir / f"{sym}_5m.csv")
                _write_bars(resample_top_of_hour(df), out_dir / f"{sym}_60m_from5m.csv")


# ---------------------------------------------------------------------------
# Events (decisions -> scan events)
# ---------------------------------------------------------------------------


@dataclass
class Event:
    sym: str
    bar_ms: int          # signal bar start (cooldown key)
    instant_ms: int      # when the scan acts (fill at first grid bar at/after this)
    date: str            # day-cap key
    is_flatten: bool
    side: Optional[str]  # "LONG" | "SHORT" | None
    stop: float = float("nan")
    target: float = float("nan")
    stop_distance: float = float("nan")
    entry_ref: float = float("nan")


def _num(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f


def events_from_live_emitter(
    path: "str | Path",
    sym: str,
    *,
    period_minutes: int = 60,
    mode: str = "both",
    shorts_from: Optional[str] = None,
    r_col: str = "target_price_r2_0",
) -> List[Event]:
    """Events from ``scripts/emit_hourly_decisions.ts`` output (#571's emitter, unchanged).

    ``mode``: ``"parity571"`` (``action_final == LONG`` only -- #571's own input),
    ``"long"``, ``"short"``, or ``"both"`` (``action_raw`` LONG/SHORT with
    ``sizing_valid``). ``shorts_from`` (YYYY-MM-DD) disables SHORT before that date.
    Every row is an event (flatten detection is per scan, not per signal), exactly as
    ``backtest/hourly_geometry.simulate_hourly_geometry`` treats them.
    """
    df = pd.read_csv(path)
    out: List[Event] = []
    for row in df.itertuples(index=False):
        ts = pd.Timestamp(row.timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        bar_ms = int(ts.value // 1_000_000)
        bar_end = bar_ms + period_minutes * 60_000
        date = ts.strftime("%Y-%m-%d")
        side: Optional[str] = None
        if mode == "parity571":
            if row.action_final == "LONG":
                side = "LONG"
        else:
            valid = str(row.sizing_valid).lower() == "true"
            if valid and row.action_raw in ("LONG", "SHORT"):
                side = row.action_raw
                if side == "SHORT" and shorts_from is not None and date < shorts_from:
                    side = None
                if mode == "long" and side == "SHORT":
                    side = None
                if mode == "short" and side == "LONG":
                    side = None
        out.append(Event(
            sym=sym, bar_ms=bar_ms, instant_ms=bar_end + SCAN_OFFSET_MIN * 60_000, date=date,
            is_flatten=is_flatten_scan(date, bar_end, period_minutes), side=side,
            stop=_num(row.stop_price), target=_num(getattr(row, r_col)),
            stop_distance=_num(row.stop_distance), entry_ref=_num(row.entry_ref),
        ))
    out.sort(key=lambda e: e.instant_ms)
    return out


def events_from_proxy_emitter(path: "str | Path", sym: str, *, mode: str = "both") -> List[Event]:
    """Events from ``emit_proxy_decisions.ts`` output (:30 grid, fill at next bar open)."""
    df = pd.read_csv(path)
    df = df[df["is_full"].astype(str).str.lower() == "true"]
    out: List[Event] = []
    for row in df.itertuples(index=False):
        ts = pd.Timestamp(row.timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        bar_ms = int(ts.value // 1_000_000)
        bar_end = bar_ms + HOUR_MS
        scan_ms = bar_end + SCAN_OFFSET_MIN * 60_000
        is_flatten = (int(row.session_close_ms) - scan_ms) <= HOUR_MS
        side: Optional[str] = None
        valid = str(row.sizing_valid).lower() == "true"
        if valid and row.action_raw in ("LONG", "SHORT"):
            side = row.action_raw
            if mode == "long" and side == "SHORT":
                side = None
            if mode == "short" and side == "LONG":
                side = None
        out.append(Event(
            sym=sym, bar_ms=bar_ms, instant_ms=bar_end, date=str(row.session_date),
            is_flatten=bool(is_flatten), side=side,
            stop=_num(row.stop_price), target=_num(row.target_price),
            stop_distance=_num(row.stop_distance), entry_ref=_num(row.entry_ref),
        ))
    out.sort(key=lambda e: e.instant_ms)
    return out


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    sym: str
    side: str
    signal_bar_ms: int
    entry_ms: int
    exit_ms: int
    entry_raw: float
    exit_raw: float
    stop: float
    target: float
    stop_distance: float
    entry_ref: float
    reason: str
    date: str

    @property
    def sign(self) -> int:
        return 1 if self.side == "LONG" else -1


def simulate(
    events_by_sym: Dict[str, List[Event]],
    bars_by_sym: Dict[str, pd.DataFrame],
    *,
    order: str,
    day_cap: int = DAY_CAP,
    max_open: Optional[int] = None,
    priority: Optional[Sequence[str]] = None,
) -> List[Trade]:
    """Sequential multi-symbol gate loop on the union time grid of ``bars_by_sym``.

    ``order="571"``: exits for bar i (positions entered strictly before bar i) are resolved
    BEFORE the scan events that act at bar i -- byte-for-byte #571's convention, used for
    the top-of-hour/5Min harness. ``order="proxy"``: scan events at bar i's open (flatten,
    entry) are processed first, then every open position (including one just entered at
    this open) is resolved against bar i -- required when the exit grid is 1h and the entry
    fills at that bar's open.

    ``max_open``: None = independent per-symbol books (live semantics, one position per
    symbol); 1 = a single position across all symbols (portfolio variant V1b), with ties at
    the same scan instant broken by ``priority`` order (disclosed, pre-registration §7).
    """
    syms = list(bars_by_sym.keys())
    prio = {s: i for i, s in enumerate(priority or syms)}
    grid = np.unique(np.concatenate([
        (bars_by_sym[s].index.asi8 // 1_000_000).astype(np.int64) for s in syms
    ]))
    n = len(grid)
    gidx = pd.DatetimeIndex(pd.to_datetime(grid, unit="ms", utc=True))
    ny_date = _ny_dates(gidx)
    arr = {}
    for s in syms:
        b = bars_by_sym[s].reindex(gidx)
        arr[s] = (
            b["Open"].to_numpy(float), b["High"].to_numpy(float),
            b["Low"].to_numpy(float), b["Close"].to_numpy(float),
        )

    evs: List[Event] = [e for s in syms for e in events_by_sym.get(s, [])]
    evs.sort(key=lambda e: (e.instant_ms, prio.get(e.sym, 999)))
    n_ev = len(evs)
    ep = 0

    pos: Dict[str, dict] = {}
    last_exit: Dict[str, int] = {}
    entries: Dict[Tuple[str, str], int] = {}
    pending_flatten: Dict[str, bool] = {}
    last_valid_close: Dict[str, Tuple[int, float]] = {}
    trades: List[Trade] = []

    def close(s: str, level: float, t: int, reason: str) -> None:
        p = pos.pop(s)
        trades.append(Trade(
            sym=s, side=p["side"], signal_bar_ms=p["signal_bar_ms"], entry_ms=p["entry_ms"],
            exit_ms=t, entry_raw=p["entry_raw"], exit_raw=float(level), stop=p["stop"],
            target=p["target"], stop_distance=p["stop_distance"], entry_ref=p["entry_ref"],
            reason=reason, date=p["date"],
        ))
        last_exit[s] = t

    def resolve_exits(i: int, t: int, inclusive: bool) -> None:
        for s in list(pos.keys()):
            p = pos[s]
            if (t > p["entry_ms"]) or (inclusive and t >= p["entry_ms"]):
                o, h, l, _ = (a[i] for a in arr[s])
                if math.isnan(o):
                    continue
                res = _resolve_bar(o, h, l, p["stop"], p["target"],
                                   BR_LONG if p["side"] == "LONG" else BR_SHORT)
                if res is not None:
                    close(s, res[0], t, res[1])

    for i in range(n):
        t = int(grid[i])
        if order == "571":
            resolve_exits(i, t, inclusive=False)
        else:
            # session-end safety for the proxy grid: a position must never cross a session
            for s in list(pos.keys()):
                if pos[s]["session"] != ny_date[i]:
                    lt, lc = last_valid_close[s]
                    close(s, lc, lt, "eod_safety")
        for s in list(pending_flatten.keys()):
            if s in pos and not math.isnan(arr[s][0][i]):
                close(s, arr[s][0][i], t, "flatten")
                pending_flatten.pop(s, None)
            elif s not in pos:
                pending_flatten.pop(s, None)

        while ep < n_ev and evs[ep].instant_ms <= t:
            e = evs[ep]
            ep += 1
            o = arr[e.sym][0][i] if e.sym in arr else float("nan")
            if e.is_flatten:
                if e.sym in pos:
                    if math.isnan(o):
                        pending_flatten[e.sym] = True
                    else:
                        close(e.sym, o, t, "flatten")
                continue
            if e.side is None or e.sym in pos or math.isnan(o):
                continue
            if e.sym in last_exit and e.bar_ms <= last_exit[e.sym]:
                continue  # cooldown
            if entries.get((e.sym, e.date), 0) >= day_cap:
                continue  # day cap
            if max_open is not None and len(pos) >= max_open:
                continue  # portfolio-level single-position variant
            pos[e.sym] = dict(
                side=e.side, signal_bar_ms=e.bar_ms, entry_ms=t, entry_raw=float(o),
                stop=e.stop, target=e.target, stop_distance=e.stop_distance,
                entry_ref=e.entry_ref, date=e.date, session=ny_date[i],
            )
            entries[(e.sym, e.date)] = entries.get((e.sym, e.date), 0) + 1

        if order != "571":
            resolve_exits(i, t, inclusive=True)
        for s in syms:
            c = arr[s][3][i]
            if not math.isnan(c):
                last_valid_close[s] = (t, float(c))

    for s in list(pos.keys()):
        lt, lc = last_valid_close[s]
        close(s, lc, lt, "end_of_window")
    trades.sort(key=lambda tr: (tr.entry_ms, tr.sym))
    return trades


# ---------------------------------------------------------------------------
# Costs and statistics
# ---------------------------------------------------------------------------


def r_at_cost(trades: Sequence[Trade], cost_bps: float) -> np.ndarray:
    """Realized R per trade with ``cost_bps`` charged on each side (entry and exit).

    Long: (exit*(1-c) - entry*(1+c)) / stop_distance. Short: mirrored. Identical to
    #571's ``r_realized`` when ``cost_bps`` = its SLIPPAGE_BPS.
    """
    c = cost_bps / 10_000.0
    out = np.empty(len(trades))
    for k, t in enumerate(trades):
        if t.side == "LONG":
            pnl = t.exit_raw * (1 - c) - t.entry_raw * (1 + c)
        else:
            pnl = t.entry_raw * (1 - c) - t.exit_raw * (1 + c)
        out[k] = pnl / t.stop_distance if t.stop_distance else float("nan")
    return out


def ret_on_notional(trades: Sequence[Trade], cost_bps: float) -> np.ndarray:
    """Per-trade return on notional (fraction), costs on both sides."""
    c = cost_bps / 10_000.0
    out = np.empty(len(trades))
    for k, t in enumerate(trades):
        if t.side == "LONG":
            out[k] = (t.exit_raw * (1 - c) - t.entry_raw * (1 + c)) / t.entry_raw
        else:
            out[k] = (t.entry_raw * (1 - c) - t.exit_raw * (1 + c)) / t.entry_raw
    return out


def breakeven_cost_bps(trades: Sequence[Trade]) -> float:
    """Per-side cost (bps) at which mean R reaches zero (linear in cost)."""
    if not trades:
        return float("nan")
    g = r_at_cost(trades, 0.0).mean()
    slope = np.mean([(t.entry_raw + t.exit_raw) / t.stop_distance for t in trades]) / 10_000.0
    return float(g / slope) if slope else float("nan")


def max_drawdown(curve: np.ndarray) -> float:
    if len(curve) == 0:
        return 0.0
    c = np.concatenate([[0.0], np.cumsum(curve)])
    return float(np.min(c - np.maximum.accumulate(c)))


def trade_stats(trades: Sequence[Trade], cost_bps: float, years: float,
                n_boot: int = 2000) -> dict:
    r = r_at_cost(trades, cost_bps)
    n = len(r)
    if n < 2:
        return dict(n=n, per_yr=n / years if years else float("nan"), mean=float("nan"),
                    ci_lo=float("nan"), ci_hi=float("nan"), win=float("nan"), pf=float("nan"),
                    cum=float(np.nansum(r)), mdd=0.0)
    ci = block_bootstrap_ci(r, n_boot=n_boot, seed=0)
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return dict(
        n=n, per_yr=n / years, mean=float(r.mean()), ci_lo=ci["ci_low"], ci_hi=ci["ci_high"],
        win=float((r > 0).mean()), pf=float(wins / losses) if losses > 0 else float("inf"),
        cum=float(r.sum()), mdd=max_drawdown(r),
    )


def daily_pnl(trades: Sequence[Trade], cost_bps: float, notional_frac: float,
              sessions: Sequence[str]) -> pd.Series:
    """Per-session P&L as a fraction of equity (non-compounding), keyed by NY entry date."""
    s = pd.Series(0.0, index=pd.Index(sorted(sessions), name="date"))
    if trades:
        r = ret_on_notional(trades, cost_bps) * notional_frac
        d = pd.Series(r, index=[t.date for t in trades]).groupby(level=0).sum()
        s = s.add(d.reindex(s.index).fillna(0.0), fill_value=0.0)
    return s


def effective_n(corr: np.ndarray) -> float:
    """Participation-ratio effective number of independent bets: (sum l)^2 / sum l^2."""
    w = np.linalg.eigvalsh(corr)
    w = np.clip(w, 0, None)
    return float(w.sum() ** 2 / (w ** 2).sum())


# ---------------------------------------------------------------------------
# Drift control (pre-registration §6.4)
# ---------------------------------------------------------------------------


def control_outcomes(proxy_csv: "str | Path", bars: pd.DataFrame, side: str) -> np.ndarray:
    """Stateless unconditional entries: every actionable full bar, same live geometry.

    Returns an array of rows ``[entry_raw, exit_raw, stop_distance, sign]`` so callers
    can price them at any cost. Fill at the next bar's open; resolution on the 1h grid
    from the fill bar onward (proxy conventions); flatten at the session's flatten scan.
    """
    df = pd.read_csv(proxy_csv)
    df = df[df["is_full"].astype(str).str.lower() == "true"].copy()
    ts = pd.to_datetime(df["timestamp"], utc=True)
    bar_ms = (ts.astype("int64") // 1_000_000).to_numpy()
    scan_ms = bar_ms + HOUR_MS + SCAN_OFFSET_MIN * 60_000
    is_flat = (df["session_close_ms"].to_numpy(np.int64) - scan_ms) <= HOUR_MS
    sess = df["session_date"].astype(str).to_numpy()
    flatten_at: Dict[str, int] = {}
    for b, f, d in zip(bar_ms, is_flat, sess):
        if f:
            flatten_at[d] = min(flatten_at.get(d, 1 << 62), int(b + HOUR_MS))
    pre = "ctrl_long" if side == "LONG" else "ctrl_short"
    stops = df[f"{pre}_stop"].to_numpy(float)
    targets = df[f"{pre}_target"].to_numpy(float)
    valid = df[f"{pre}_valid"].astype(str).str.lower().to_numpy() == "true"
    gms = (bars.index.asi8 // 1_000_000)
    o = bars["Open"].to_numpy(float)
    h = bars["High"].to_numpy(float)
    lo = bars["Low"].to_numpy(float)
    pos_of = {int(m): k for k, m in enumerate(gms)}
    br = BR_LONG if side == "LONG" else BR_SHORT
    rows = []
    for k in range(len(df)):
        if is_flat[k] or not valid[k]:
            continue
        j = pos_of.get(int(bar_ms[k] + HOUR_MS))
        fl = flatten_at.get(sess[k])
        if j is None or fl is None:
            continue
        entry = o[j]
        sd = abs(entry - stops[k])
        exit_level = None
        jj = j
        while jj < len(gms):
            if gms[jj] >= fl:
                exit_level = o[jj]
                break
            res = _resolve_bar(o[jj], h[jj], lo[jj], stops[k], targets[k], br)
            if res is not None:
                exit_level = res[0]
                break
            jj += 1
        if exit_level is None:
            continue
        rows.append((entry, exit_level, sd, 1 if side == "LONG" else -1))
    return np.asarray(rows, dtype=float).reshape(-1, 4)


def control_r(rows: np.ndarray, cost_bps: float) -> np.ndarray:
    c = cost_bps / 10_000.0
    entry, exit_, sd, sign = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3]
    long_pnl = exit_ * (1 - c) - entry * (1 + c)
    short_pnl = entry * (1 - c) - exit_ * (1 + c)
    return np.where(sign > 0, long_pnl, short_pnl) / sd
