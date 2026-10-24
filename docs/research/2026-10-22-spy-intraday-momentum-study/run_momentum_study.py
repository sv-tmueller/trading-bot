"""SPY market intraday momentum study (Gao, Han, Li & Zhou 2018) -- runner.

Research-only. Local files only: no network, no broker, no LLM. Every definition applied here
is frozen in ``docs/research/2026-10-22-spy-intraday-momentum-preregistration.md`` (section
numbers in comments refer to it). Never imported by ``supabase/functions/``.

Usage::

    CLAUDE_AGENT_NO_BROKER=1 venv/bin/python \
        docs/research/2026-10-22-spy-intraday-momentum-study/run_momentum_study.py \
        --bars5 data/intraday/SPY_5min.csv --b0-decisions <scratch>/dec/SPY_sip_60m.csv \
        --json-out <scratch>/momentum_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import vendored_multi_symbol_hourly as msh  # noqa: E402
from backtest.intraday_data import describe_power, load_local  # noqa: E402
from backtest.overfitting_gate import (  # noqa: E402
    block_bootstrap_ci, block_bootstrap_uplift_ci, evaluate_gate,
)

NY = "America/New_York"
NOTIONAL = 0.10            # SIZING_NOTIONAL_CAP_PCT (§4)
EQUITY = 1_020_000.0       # $ (§4)
COSTS = (0.0, 0.5, 1.0, 2.0)
PRIMARY_COST = 1.0
IS_END = "2020-12-31"
POST_START = "2018-01-01"
N_BOOT = 2000

HALF_DAYS = frozenset((  # §1.2
    "2016-11-25", "2017-07-03", "2017-11-24", "2018-07-03", "2018-11-23", "2018-12-24",
    "2019-07-03", "2019-11-29", "2019-12-24", "2020-11-27", "2020-12-24", "2021-11-26",
    "2022-11-25", "2023-07-03", "2023-11-24", "2024-07-03", "2024-11-29", "2024-12-24",
    "2025-07-03", "2025-11-28", "2025-12-24",
))


def ex_div_dates() -> List[str]:
    """§1.3: third Friday of Mar/Jun/Sep/Dec 2016-03 .. 2026-06, 2026-06-19 -> 2026-06-18."""
    out = []
    for y in range(2016, 2027):
        for mo in (3, 6, 9, 12):
            d = pd.Timestamp(y, mo, 1)
            d = d + pd.Timedelta(days=(4 - d.weekday()) % 7 + 14)
            s = d.strftime("%Y-%m-%d")
            if s == "2026-06-19":
                s = "2026-06-18"
            if s <= "2026-08-12":
                out.append(s)
    return out


EX_DIV = frozenset(ex_div_dates())

CONFIGS = [(v, e) for v in ("V1", "V2", "V3") for e in ("E1", "E2")]


def hdr(t: str) -> None:
    print()
    print("=" * 100)
    print(t)
    print("=" * 100)


# ---------------------------------------------------------------------------
# §1 session table
# ---------------------------------------------------------------------------


def build_sessions(bars: pd.DataFrame) -> pd.DataFrame:
    loc = bars.index.tz_convert(NY)
    df = bars.copy()
    df["d"] = loc.strftime("%Y-%m-%d")
    df["m"] = loc.hour * 60 + loc.minute
    df = df[(df["m"] >= 570) & (df["m"] <= 960)]  # RTH plus the 16:00 bar (X_moc)
    piv = {}
    for col in ("Open", "Close"):
        piv[col] = df.pivot_table(index="d", columns="m", values=col, aggfunc="first")
    O, C = piv["Open"], piv["Close"]
    days = sorted(set(df.loc[df["m"] < 960, "d"]))

    def g(tab, m):
        return tab[m].reindex(days) if m in tab.columns else pd.Series(np.nan, index=days)

    s = pd.DataFrame(index=pd.Index(days, name="date"))
    s["half"] = [d in HALF_DAYS for d in days]
    s["close_bar"] = np.where(s["half"], g(C, 775), g(C, 955))  # 12:55 / 15:55 close
    s["C_prev"] = s["close_bar"].shift(1)
    s["O930"] = g(O, 570)
    s["P10"] = g(C, 595)
    s["P15"] = g(C, 895)
    s["P1530"] = g(C, 925)
    s["E_in"] = g(O, 930)
    s["E_in_late"] = g(O, 935)
    s["X_mkt"] = g(C, 955)
    moc = g(O, 960)
    s["moc_fallback"] = moc.isna()
    s["X_moc"] = moc.fillna(s["X_mkt"])
    s["C_d"] = s["X_mkt"]
    # RV1: 09:30 open->close, then close-to-close for 09:35 .. 09:55 (§3 V3)
    lr = [np.log(g(C, 570) / g(O, 570))]
    for m in range(575, 600, 5):
        lr.append(np.log(g(C, m) / g(C, m - 5)))
    s["RV1"] = np.sqrt(sum(x ** 2 for x in lr))
    s["r1"] = s["P10"] / s["C_prev"] - 1
    s["r12"] = s["P1530"] / s["P15"] - 1
    s["r13"] = s["C_d"] / s["P1530"] - 1
    s["overnight"] = s["O930"] / s["C_prev"] - 1
    s["ex_div"] = [d in EX_DIV for d in days]
    # §1.2: eligibility depends ONLY on the price-point bars. RV1 is undefined when one of the
    # six 09:30-09:55 bars is missing (e.g. 2020-03 circuit-breaker halts); V3 is then flat
    # that day, but the session stays eligible for V1/V2 and the regressions.
    need = ["C_prev", "P10", "P15", "P1530", "E_in", "X_mkt"]
    s["eligible"] = (~s["half"]) & s[need].notna().all(axis=1)
    # V3 threshold: 2/3 quantile of RV1 over the previous up-to-252 ELIGIBLE sessions (>=120)
    el = s[s["eligible"]]
    thr = el["RV1"].shift(1).rolling(252, min_periods=120).quantile(2 / 3)
    s["rv_thr"] = thr.reindex(s.index)
    return s


# ---------------------------------------------------------------------------
# §2 regressions with Newey-West HAC
# ---------------------------------------------------------------------------


def nw_lag(t: int) -> int:
    return int(math.floor(4 * (t / 100.0) ** (2.0 / 9.0)))


def ols_hac(y: np.ndarray, X: np.ndarray, lag: Optional[int] = None) -> dict:
    t, k = X.shape
    L = nw_lag(t) if lag is None else lag
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    u = y - X @ beta
    xu = X * u[:, None]
    S = xu.T @ xu
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        G = xu[l:].T @ xu[:-l]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv
    se = np.sqrt(np.diag(V))
    r2 = 1.0 - (u @ u) / np.sum((y - y.mean()) ** 2)
    return dict(beta=beta, se=se, t=beta / se, r2=r2, n=t, lag=L)


def reg(s: pd.DataFrame, xs: Sequence[str]) -> dict:
    y = s["r13"].to_numpy(float)
    X = np.column_stack([np.ones(len(s))] + [s[c].to_numpy(float) for c in xs])
    return ols_hac(y, X)


def fmt_reg(label: str, r: dict, names: Sequence[str]) -> str:
    parts = [f"{nm}: b={r['beta'][i+1]:+.4f} t={r['t'][i+1]:+.2f}" for i, nm in enumerate(names)]
    return f"{label:<34s} n={r['n']:5d} L={r['lag']:2d} " + "  ".join(parts) + f"  R2={r['r2']*100:.2f}%"


# ---------------------------------------------------------------------------
# §3 trades
# ---------------------------------------------------------------------------


def signals(s: pd.DataFrame, variant: str) -> pd.Series:
    sg1 = np.sign(s["r1"])
    if variant == "V1":
        out = sg1
    elif variant == "V2":
        out = sg1.where(np.sign(s["r12"]) == sg1, 0.0)
    elif variant == "V3":
        hi = s["RV1"] > s["rv_thr"]
        out = sg1.where(hi.fillna(False), 0.0)
    elif variant == "LONG":
        out = pd.Series(1.0, index=s.index)
    else:
        raise ValueError(variant)
    return out.fillna(0.0)


def trades_for(s: pd.DataFrame, variant: str, exit_model: str, *, entry_col: str = "E_in",
               side: str = "both") -> pd.DataFrame:
    sig = signals(s, variant)
    if side == "long":
        sig = sig.where(sig > 0, 0.0)
    elif side == "short":
        sig = sig.where(sig < 0, 0.0)
    x = s["X_mkt"] if exit_model == "E1" else s["X_moc"]
    t = pd.DataFrame({"sign": sig, "E": s[entry_col], "X": x})
    t = t[(t["sign"] != 0) & t["E"].notna() & t["X"].notna()]
    return t


def net_ret(t: pd.DataFrame, cost_bps: float) -> pd.Series:
    c = cost_bps / 1e4
    long_ = (t["X"] * (1 - c) - t["E"] * (1 + c)) / t["E"]
    short = (t["E"] * (1 - c) - t["X"] * (1 + c)) / t["E"]
    return pd.Series(np.where(t["sign"] > 0, long_, short), index=t.index)


def daily_series(ret: pd.Series, sessions: Sequence[str]) -> pd.Series:
    d = pd.Series(0.0, index=pd.Index(sessions))
    return d.add(ret.groupby(level=0).sum().reindex(d.index).fillna(0.0) * NOTIONAL, fill_value=0.0)


def sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 1e-12 else 0.0


def sharpe_ci(x: np.ndarray, n_boot: int = N_BOOT, seed: int = 0) -> tuple:
    n = len(x)
    L = max(1, round(n ** (1 / 3)))
    rng = np.random.default_rng(seed)
    nb = math.ceil(n / L)
    out = np.empty(n_boot)
    for i in range(n_boot):
        st = rng.integers(0, n - L + 1, size=nb)
        r = np.concatenate([x[k:k + L] for k in st])[:n]
        out[i] = sharpe(r) * math.sqrt(252)
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def max_dd(daily: np.ndarray) -> float:
    c = np.concatenate([[0.0], np.cumsum(daily)])
    return float(np.min(c - np.maximum.accumulate(c)))


def stats(ret: pd.Series, sessions: Sequence[str], r_unit_bps: float) -> dict:
    """Per-trade + daily stats. ``ret``: per-trade net return on notional, indexed by date."""
    n = len(ret)
    yrs = len(sessions) / 252.0
    daily = daily_series(ret, sessions).to_numpy()
    out = dict(n=n, per_yr=n / yrs if yrs else float("nan"))
    if n >= 2:
        bps = ret.to_numpy() * 1e4
        ci = block_bootstrap_ci(bps, n_boot=N_BOOT, seed=0)
        wins, losses = bps[bps > 0].sum(), -bps[bps < 0].sum()
        out.update(mean_bps=float(bps.mean()), ci_lo=ci["ci_low"], ci_hi=ci["ci_high"],
                   mean_R=float(bps.mean() / r_unit_bps), win=float((bps > 0).mean()),
                   pf=float(wins / losses) if losses > 0 else float("inf"))
    else:
        out.update(mean_bps=float("nan"), ci_lo=float("nan"), ci_hi=float("nan"),
                   mean_R=float("nan"), win=float("nan"), pf=float("nan"))
    sh = sharpe(daily) * math.sqrt(252)
    lo, hi = sharpe_ci(daily) if n >= 2 else (float("nan"), float("nan"))
    out.update(sharpe=sh, sh_lo=lo, sh_hi=hi, total_pct=float(daily.sum() * 100),
               total_usd=float(daily.sum() * EQUITY), mdd_pct=max_dd(daily) * 100,
               mdd_usd=max_dd(daily) * EQUITY)
    return out


def fmt(label: str, st: dict) -> str:
    return (f"{label:<30s} n={st['n']:5d} tr/yr={st['per_yr']:6.1f} mean={st['mean_bps']:+6.2f}bps "
            f"[{st['ci_lo']:+6.2f},{st['ci_hi']:+6.2f}] R={st['mean_R']:+.3f} win={st['win']*100:5.1f}% "
            f"PF={st['pf']:.2f} Sh={st['sharpe']:+.2f}[{st['sh_lo']:+.2f},{st['sh_hi']:+.2f}] "
            f"tot={st['total_pct']:+6.2f}% (${st['total_usd']:+,.0f}) mDD={st['mdd_pct']:.2f}% "
            f"(${st['mdd_usd']:,.0f})")


def breakeven(t: pd.DataFrame) -> float:
    return float(net_ret(t, 0.0).mean() * 1e4 / 2.0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    assert os.environ.get("CLAUDE_AGENT_NO_BROKER") == "1", "export CLAUDE_AGENT_NO_BROKER=1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars5", required=True)
    ap.add_argument("--b0-decisions", required=True)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)
    R: Dict[str, object] = {}

    hdr("§1 data")
    raw = load_local(a.bars5)
    pw = describe_power(raw)
    print("power:", pw.summary())
    R["power"] = pw.summary()
    s_all = build_sessions(raw)
    print(f"sessions={len(s_all)} half-days={int(s_all['half'].sum())} "
          f"eligible={int(s_all['eligible'].sum())} moc_fallback(eligible)="
          f"{int((s_all['moc_fallback'] & s_all['eligible']).sum())}")
    excl = s_all[~s_all["eligible"] & ~s_all["half"]].index.tolist()
    print("non-half-day exclusions:", excl)

    hdr("§1.3 D1 dividend-neutrality check")
    el = s_all[s_all["eligible"]]
    ov_ex = el.loc[el["ex_div"], "overnight"] * 1e4
    ov_no = el.loc[~el["ex_div"], "overnight"] * 1e4
    d1 = float(ov_ex.mean() - ov_no.mean())
    print(f"ex-div eligible sessions={len(ov_ex)} mean overnight={ov_ex.mean():+.2f}bps; "
          f"others mean={ov_no.mean():+.2f}bps; D1={d1:+.2f}bps (switch if < -20)")
    primary_excl_exdiv = d1 < -20
    print("primary sample:", "ex-dates EXCLUDED" if primary_excl_exdiv else "ex-dates included")
    R["D1_bps"] = d1
    s = el[~el["ex_div"]] if primary_excl_exdiv else el
    sessions = list(s.index)

    hdr("§2 predictive regressions (HAC Newey-West, Bartlett)")
    regs = {}
    for label, sub in (("full 2016-2026", s), ("pre-2018 (2016-2017)", s[s.index < POST_START]),
                       ("post-2018 (2018-2026)", s[s.index >= POST_START]),
                       ("IS 2016-2020", s[s.index <= IS_END]), ("OOS 2021-2026", s[s.index > IS_END]),
                       ("full, ex-div excluded", s[~s["ex_div"]])):
        r1 = reg(sub, ["r1"])
        r12 = reg(sub, ["r12"])
        rb = reg(sub, ["r1", "r12"])
        print(fmt_reg(label + " | r1", r1, ["r1"]))
        print(fmt_reg(label + " | r12", r12, ["r12"]))
        print(fmt_reg(label + " | r1+r12", rb, ["r1", "r12"]))
        regs[label] = dict(
            n=r1["n"], b1=r1["beta"][1], t1=r1["t"][1], r2_1=r1["r2"],
            b12=r12["beta"][1], t12=r12["t"][1], r2_12=r12["r2"],
            both_b1=rb["beta"][1], both_t1=rb["t"][1], both_b12=rb["beta"][2],
            both_t12=rb["t"][2], r2_both=rb["r2"],
        )
    # high-vol diagnostic
    hv = s[s["RV1"] > s["rv_thr"]]
    lv = s[(s["RV1"] <= s["rv_thr"])]
    for label, sub in (("high-RV1 tercile days", hv), ("other days (thr known)", lv)):
        r1 = reg(sub, ["r1"])
        print(fmt_reg(label + " | r1", r1, ["r1"]))
        regs[label] = dict(n=r1["n"], b1=r1["beta"][1], t1=r1["t"][1], r2_1=r1["r2"])
    # interaction (decay) test
    sub = s.copy()
    sub["D"] = (sub.index >= POST_START).astype(float)
    sub["r1D"] = sub["r1"] * sub["D"]
    ri = reg(sub, ["r1", "D", "r1D"])
    print(fmt_reg("interaction r1 + D_post + r1*D_post", ri, ["r1", "D", "r1D"]))
    regs["interaction"] = dict(b_r1=ri["beta"][1], t_r1=ri["t"][1], b_r1D=ri["beta"][3], t_r1D=ri["t"][3])
    print("by year (r13 ~ r1):")
    yrs_reg = {}
    for y in range(2016, 2027):
        sub = s[s.index.str.startswith(str(y))]
        r1 = reg(sub, ["r1"])
        yrs_reg[y] = dict(n=r1["n"], b1=r1["beta"][1], t1=r1["t"][1], r2=r1["r2"])
        print(f"  {y}: n={r1['n']:4d} b1={r1['beta'][1]:+.4f} t={r1['t'][1]:+.2f} R2={r1['r2']*100:5.2f}%")
    regs["by_year"] = yrs_reg
    R["regressions"] = regs
    print(f"unconditional r13: mean={s['r13'].mean()*1e4:+.2f}bps sd={s['r13'].std()*1e4:.2f}bps; "
          f"r1 sd={s['r1'].std()*1e4:.1f}bps; corr(r1, r13)={s['r1'].corr(s['r13']):+.4f}")

    hdr("B0 replay (hourly candlestick rule) -- for R-unit and head-to-head")
    ev = msh.events_from_live_emitter(a.b0_decisions, "SPY", mode="both")
    b0_bars = msh.load_bars(a.bars5)
    b0 = msh.simulate({"SPY": ev}, {"SPY": b0_bars}, order="571")
    r_unit = float(np.median([t.stop_distance / t.entry_raw * 1e4 for t in b0]))
    print(f"B0 trades={len(b0)}; median stop distance = {r_unit:.2f} bps (R-equivalent unit)")
    R["r_unit_bps"] = r_unit
    all_sessions = list(s_all.index)

    hdr("§5 configurations x costs (primary sample)")
    tr = {c: trades_for(s, *c) for c in CONFIGS}
    res = {}
    for c in CONFIGS:
        name = f"{c[0]}-{c[1]}"
        res[name] = {}
        for cost in COSTS:
            st = stats(net_ret(tr[c], cost), sessions, r_unit)
            res[name][cost] = st
            print(fmt(f"{name} @{cost}bps", st))
        be = breakeven(tr[c])
        res[name]["breakeven"] = be
        print(f"{name} break-even cost = {be:+.2f} bps/side")
    R["configs"] = {k: {str(kk): vv for kk, vv in v.items()} for k, v in res.items()}

    hdr("diagnostics (non-trial)")
    diag = {}
    t_long = trades_for(s, "LONG", "E1")
    for cost in (0.0, PRIMARY_COST):
        st = stats(net_ret(t_long, cost), sessions, r_unit)
        diag[f"always_long@{cost}"] = st
        print(fmt(f"always-long 15:30->close @{cost}", st))
    for c in CONFIGS:
        for side in ("long", "short"):
            t = trades_for(s, c[0], c[1], side=side)
            st = stats(net_ret(t, PRIMARY_COST), sessions, r_unit)
            diag[f"{c[0]}-{c[1]}_{side}@1"] = st
            print(fmt(f"{c[0]}-{c[1]} {side}-only @1", st))
    for c in CONFIGS:
        t = trades_for(s, c[0], c[1], entry_col="E_in_late")
        for cost in (0.0, PRIMARY_COST):
            st = stats(net_ret(t, cost), sessions, r_unit)
            diag[f"{c[0]}-{c[1]}_late@{cost}"] = st
            print(fmt(f"{c[0]}-{c[1]} entry 15:35 @{cost}", st))
    s_nx = s[~s["ex_div"]]
    for c in CONFIGS:
        t = trades_for(s_nx, *c)
        for cost in (0.0, PRIMARY_COST):
            st = stats(net_ret(t, cost), list(s_nx.index), r_unit)
            diag[f"{c[0]}-{c[1]}_R2exdiv@{cost}"] = st
            print(fmt(f"{c[0]}-{c[1]} R2 ex-div excl @{cost}", st))
    R["diagnostics"] = diag

    hdr("§5 IS / OOS (1 bp/side and 0 bp)")
    split = {}
    for c in CONFIGS:
        name = f"{c[0]}-{c[1]}"
        for lab, cond in (("IS", s.index <= IS_END), ("OOS", s.index > IS_END)):
            sub = s[cond]
            t = trades_for(sub, *c)
            for cost in (0.0, PRIMARY_COST):
                st = stats(net_ret(t, cost), list(sub.index), r_unit)
                split[f"{name}_{lab}@{cost}"] = st
                print(fmt(f"{name} {lab} @{cost}", st))
    R["split"] = split

    hdr("§5 by year (mean net bps/trade @1bp, n)")
    by_year = {}
    for c in CONFIGS:
        name = f"{c[0]}-{c[1]}"
        ret = net_ret(tr[c], PRIMARY_COST)
        row = {}
        for y in range(2016, 2027):
            r = ret[ret.index.str.startswith(str(y))]
            row[y] = (float(r.mean() * 1e4) if len(r) else float("nan"), int(len(r)))
        by_year[name] = row
        print(name, " ".join(f"{y}:{v[0]:+.1f}({v[1]})" for y, v in row.items()))
    R["by_year"] = by_year

    hdr("§6 overfitting gate (N=6, 1 bp/side, daily P&L, baseline = cash)")
    mat = np.column_stack([daily_series(net_ret(tr[c], PRIMARY_COST), sessions).to_numpy()
                           for c in CONFIGS])
    sh = [sharpe(mat[:, j]) for j in range(mat.shape[1])]
    best = int(np.argmax(sh))
    best_name = f"{CONFIGS[best][0]}-{CONFIGS[best][1]}"
    print("non-annualized daily Sharpes:", {f"{c[0]}-{c[1]}": round(v, 4) for c, v in zip(CONFIGS, sh)})
    print("best by full-sample Sharpe:", best_name)
    best_daily = pd.Series(mat[:, best], index=pd.Index(sessions))
    monthly = best_daily.groupby(best_daily.index.str[:7]).sum().to_numpy()
    g = evaluate_gate(returns_best=mat[:, best], all_trial_sharpes=sh, perf_matrix=mat,
                      uplifts=monthly, pbo_n_splits=16)
    print(f"DSR={g['dsr']:.4f} (sr_hat={g['dsr_result']['sr_hat']:+.4f}, sr*={g['dsr_result']['sr_star']:.4f}) "
          f"PBO={g['pbo']:.4f} monthly mean={g['bootstrap_result']['point']*100:+.4f}% "
          f"CI=[{g['bootstrap_result']['ci_low']*100:+.4f}%,{g['bootstrap_result']['ci_high']*100:+.4f}%] "
          f"-> {'PASS' if g['passed'] else 'FAIL'} {g['reasons']}")
    R["gate"] = dict(best=best_name, sharpes=dict(zip([f"{c[0]}-{c[1]}" for c in CONFIGS], sh)),
                     dsr=g["dsr"], sr_hat=g["dsr_result"]["sr_hat"], sr_star=g["dsr_result"]["sr_star"],
                     pbo=g["pbo"], m_point=g["bootstrap_result"]["point"],
                     m_lo=g["bootstrap_result"]["ci_low"], m_hi=g["bootstrap_result"]["ci_high"],
                     passed=g["passed"], reasons=g["reasons"])

    hdr("§5 walk-forward (expanding, yearly; select max Sharpe @1bp on prior sessions)")
    wf_rows, wf_total = [], 0.0
    dfm = pd.DataFrame(mat, index=pd.Index(sessions), columns=[f"{c[0]}-{c[1]}" for c in CONFIGS])
    for y in range(2018, 2027):
        train = dfm[dfm.index < f"{y}-01-01"]
        test = dfm[dfm.index.str.startswith(str(y))]
        shs = {col: sharpe(train[col].to_numpy()) for col in dfm.columns}
        pick = max(shs, key=shs.get)
        pnl = float(test[pick].sum())
        v1 = float(test["V1-E1"].sum())
        wf_total += pnl
        wf_rows.append((y, pick, pnl, v1))
        print(f"  {y}: pick={pick} (train Sh={shs[pick]*math.sqrt(252):+.2f}) test P&L={pnl*100:+.3f}% "
              f"(${pnl*EQUITY:+,.0f}); V1-E1 same year {v1*100:+.3f}%")
    print(f"walk-forward concatenated OOS P&L = {wf_total*100:+.3f}% (${wf_total*EQUITY:+,.0f})")
    R["walk_forward"] = dict(rows=wf_rows, total=wf_total)

    hdr("§7 head-to-head vs B0 (same 10% notional, same costs, 2016-01-04..2026-08-12)")
    h2h = {}
    b0_dates = [t.date for t in b0]
    b0_yrs_sessions = all_sessions
    for cost in COSTS:
        b0_ret = pd.Series(msh.ret_on_notional(b0, cost), index=b0_dates)
        stb = stats(b0_ret, b0_yrs_sessions, r_unit)
        stv = stats(net_ret(tr[("V1", "E1")], cost), all_sessions, r_unit)
        stbest = stats(net_ret(tr[CONFIGS[best]], cost), all_sessions, r_unit)
        h2h[cost] = dict(B0=stb, V1E1=stv, best=stbest)
        print(fmt(f"B0 candlestick @{cost}", stb))
        print(fmt(f"V1-E1 @{cost}", stv))
        print(fmt(f"{best_name} @{cost}", stbest))
    b0_daily = daily_series(pd.Series(msh.ret_on_notional(b0, PRIMARY_COST), index=b0_dates), all_sessions)
    for lab, c in (("V1-E1", ("V1", "E1")), (best_name, CONFIGS[best])):
        md = daily_series(net_ret(tr[c], PRIMARY_COST), all_sessions)
        corr = float(np.corrcoef(md.to_numpy(), b0_daily.to_numpy())[0, 1])
        mm = md.groupby(md.index.str[:7]).sum()
        bm = b0_daily.groupby(b0_daily.index.str[:7]).sum()
        u = block_bootstrap_uplift_ci(mm.to_numpy(), bm.to_numpy(), n_boot=N_BOOT, seed=0)
        h2h[f"{lab}_vs_B0"] = dict(corr=corr, point=u["point"], lo=u["ci_low"], hi=u["ci_high"])
        print(f"{lab} minus B0 monthly P&L @1bp: mean {u['point']*100:+.4f}% "
              f"CI [{u['ci_low']*100:+.4f}%, {u['ci_high']*100:+.4f}%]; daily corr {corr:+.3f}")
    R["h2h"] = {str(k): v for k, v in h2h.items()}

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(R, indent=1, default=lambda o: (
            o.tolist() if isinstance(o, np.ndarray) else float(o) if isinstance(o, np.floating)
            else int(o) if isinstance(o, np.integer) else str(o))))
        print(f"\nwrote {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
