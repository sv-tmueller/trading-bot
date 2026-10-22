"""Runner for the 2026-10-22 multi-symbol hourly study: parity gates P0b-P0d, then the study.

Research-only, local files only (no network, no broker). Consumes the decision CSVs written by
``run_emitters.py`` (+ ``SPY_sip_60m.csv`` from the unchanged #571 emitter) and the prepared
bar files from ``prepare_inputs.py``. Every definition it applies is frozen in
``docs/research/2026-10-22-multi-symbol-hourly-preregistration.md``.

Usage::

    CLAUDE_AGENT_NO_BROKER=1 venv/bin/python \
        docs/research/2026-10-22-multi-symbol-hourly-study/run_multi_symbol_study.py \
        --inputs <scratch>/inputs --dec <scratch>/dec --sip-5m data/intraday/SPY_5min.csv \
        --journal docs/trading-journal/daily-verification.jsonl --raw <scratch>/bars \
        --stage all
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import multi_symbol_hourly as msh  # noqa: E402
from backtest.overfitting_gate import (  # noqa: E402
    block_bootstrap_ci, deflated_sharpe_ratio, evaluate_gate,
    probability_of_backtest_overfitting,
)

C0, C2, C3, C1 = 0.0, 1.0, 2.5, 5.0
COSTS = (("C0", C0), ("C2", C2), ("C3", C3), ("C1", C1))
SHORTS_FROM = "2026-09-03"
IS_END = "2025-04-30"
WF_STEPS = (
    ("W1", "2024-12-01", "2025-05-31"),
    ("W2", "2025-06-01", "2025-11-30"),
    ("W3", "2025-12-01", "2026-05-31"),
    ("W4", "2026-06-01", "2026-10-21"),
)
PRIORITY_TOP = ("SPY",) + msh.TOP10
PRIORITY_ETF = ("SPY",) + msh.ETFS
EQUITY = 1_020_000.0


def hdr(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def fmt_stats(label: str, s: dict) -> str:
    return (f"{label:<26s} n={s['n']:5d} tr/yr={s['per_yr']:7.1f} meanR={s['mean']:+.3f} "
            f"CI=[{s['ci_lo']:+.3f},{s['ci_hi']:+.3f}] win={s['win']*100:5.1f}% "
            f"PF={s['pf']:.2f} cumR={s['cum']:+8.1f} maxDD_R={s['mdd']:7.1f}")


def sessions_of(bars: pd.DataFrame) -> List[str]:
    return sorted(set(msh._ny_dates(bars.index)))


# ---------------------------------------------------------------------------
# P0b: live journal parity
# ---------------------------------------------------------------------------


def load_journal(path: Path):
    days, trades = {}, {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        m = rec.get("metrics") or {}
        days[rec["date"]] = m
        for t in (rec.get("reflection") or {}).get("trades") or []:
            trades[t["entry_order_id"]] = t
    return days, sorted(trades.values(), key=lambda t: t["entry_fill_time"])


def stage_p0b(a) -> bool:
    hdr("P0b -- H_live on Yahoo SPY (top-of-hour, 5m fills/exits) vs the live journal")
    days, live = load_journal(Path(a.journal))
    ev = msh.events_from_live_emitter(Path(a.dec) / "SPY_live60.csv", "SPY", mode="both",
                                      shorts_from=SHORTS_FROM)
    bars = msh.load_bars(Path(a.inputs) / "SPY_5m.csv")
    sim = msh.simulate({"SPY": ev}, {"SPY": bars}, order="571")
    window = sorted(d for d, m in days.items()
                    if "2026-08-03" <= d <= "2026-10-21" and (m.get("evaluated_bars") or 0) > 0)
    sim_by_day = defaultdict(Counter)
    for t in sim:
        sim_by_day[t.date][t.side] += 1
    agree = 0
    rows = []
    for d in window:
        dc = days[d].get("decision_counts") or {}
        lv = (dc.get("LONG", 0), dc.get("SHORT", 0))
        sv = (sim_by_day[d]["LONG"], sim_by_day[d]["SHORT"])
        agree += lv == sv
        rows.append((d, lv, sv))
    day_frac = agree / len(window)
    for d, lv, sv in rows:
        flag = "" if lv == sv else "   <-- differs"
        print(f"  {d} live(L,S)={lv} sim(L,S)={sv}{flag}")
    print(f"day-level agreement: {agree}/{len(window)} = {day_frac:.3f} (threshold >= 0.70)")

    sim_key = {}
    for t in sim:
        ts = pd.Timestamp(t.entry_ms, unit="ms", tz="UTC")
        sim_key[(t.date, ts.hour, t.side)] = t
    r_sim_all = dict(zip([id(t) for t in sim], msh.r_at_cost(sim, C2)))
    matched, diffs = 0, []
    live_win = [t for t in live if "2026-08-13" <= t["entry_fill_time"][:10] <= "2026-10-21"]
    for t in live_win:
        ts = pd.Timestamp(t["entry_fill_time"])
        k = (ts.strftime("%Y-%m-%d"), ts.hour, t["side"])
        st = sim_key.get(k)
        if st is not None:
            matched += 1
            diffs.append(abs(r_sim_all[id(st)] - t["realized_r"]))
            mark = f"sim R={r_sim_all[id(st)]:+.2f} ({st.reason})"
        else:
            mark = "UNMATCHED"
        print(f"  live {k[0]} {k[1]:02d}h {k[2]:5s} R={t['realized_r']:+.2f} ({t['exit_type']}) -> {mark}")
    trade_frac = matched / len(live_win)
    med = float(np.median(diffs)) if diffs else float("nan")
    sim_win = [t for t in sim if "2026-08-13" <= t.date <= "2026-10-21" and t.date in set(window)]
    print(f"trade-level match: {matched}/{len(live_win)} = {trade_frac:.3f} "
          f"(hard >= 0.60; caveat band 0.60-0.75); sim trades same window = {len(sim_win)}")
    print(f"matched |R_sim(C2) - R_live| median = {med:.3f}R (threshold <= 0.25R)")
    live_sum = sum(t["realized_r"] for t in live_win)
    sim_sum = float(msh.r_at_cost(sim_win, C2).sum())
    print(f"window cumulative R: live={live_sum:+.2f} (n={len(live_win)})  sim C2={sim_sum:+.2f} (n={len(sim_win)})")
    ok = day_frac >= 0.70 and trade_frac >= 0.60 and med <= 0.25
    print(f"P0b: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# P0c / P0d
# ---------------------------------------------------------------------------


def run_live_sip(a, mode="both"):
    ev = msh.events_from_live_emitter(Path(a.dec) / "SPY_sip_60m.csv", "SPY", mode=mode)
    bars = msh.load_bars(a.sip_5m)
    return msh.simulate({"SPY": ev}, {"SPY": bars}, order="571")


def run_proxy(dec_csv: Path, bars_csv: Path, sym: str, mode="both"):
    ev = msh.events_from_proxy_emitter(dec_csv, sym, mode=mode)
    bars = msh.load_bars(bars_csv)
    return msh.simulate({sym: ev}, {sym: bars}, order="proxy"), bars


def stage_p0c(a, cache) -> bool:
    hdr("P0c -- construction distortion on SPY SIP 2016-01-04..2026-08-12: H_proxy vs H_live")
    live = run_live_sip(a)
    prox, pbars = run_proxy(Path(a.dec) / "SPY_sip_proxy.csv",
                            Path(a.inputs) / "SPY_sip_1h_proxy.csv", "SPY")
    cache["B0_live"] = live
    yrs = len(sessions_of(pbars)) / 252
    sl = msh.trade_stats(live, C2, yrs)
    sp = msh.trade_stats(prox, C2, yrs)
    print(fmt_stats("H_live  SIP (C2)", sl))
    print(fmt_stats("H_proxy SIP (C2)", sp))
    dm, dw = sp["mean"] - sl["mean"], (sp["win"] - sl["win"]) * 100
    print(f"delta mean R = {dm:+.3f} (|.| <= 0.10)  delta win = {dw:+.1f} pp (|.| <= 5)  "
          f"trades/yr ratio = {sp['per_yr']/sl['per_yr']:.2f}")
    print(f"exits live={dict(Counter(t.reason for t in live))} proxy={dict(Counter(t.reason for t in prox))}")
    ok = abs(dm) <= 0.10 and abs(dw) <= 5
    print(f"P0c: {'PASS' if ok else 'FAIL'}")
    return ok


def stage_p0d(a) -> bool:
    hdr("P0d -- Yahoo vs SIP on the proxy grid, SPY, 2023-11-24..2026-08-12")
    y = msh.load_bars(Path(a.inputs) / "SPY_1h_proxy.csv")
    s = msh.load_bars(Path(a.inputs) / "SPY_sip_1h_proxy.csv")
    end = "2026-08-12"
    y = y[msh._ny_dates(y.index) <= end]
    s = s[s.index >= y.index[0]]
    j = y.join(s, how="inner", lsuffix="_y", rsuffix="_s")
    dclose = (j["Close_y"] / j["Close_s"] - 1).abs() * 1e4
    print(f"matched bars={len(j)} (yahoo {len(y)}, sip {len(s)}); median |dClose|={dclose.median():.2f} bps, "
          f"p95={dclose.quantile(.95):.2f} bps")
    dy = pd.read_csv(Path(a.dec) / "SPY_proxy.csv")
    ds = pd.read_csv(Path(a.dec) / "SPY_sip_proxy.csv")
    dy["timestamp"] = pd.to_datetime(dy["timestamp"], utc=True)
    ds["timestamp"] = pd.to_datetime(ds["timestamp"], utc=True)
    m = dy.merge(ds, on="timestamp", suffixes=("_y", "_s"))
    m = m[m["session_date_y"] <= end]
    fire = m[m["action_raw_y"].isin(["LONG", "SHORT"]) | m["action_raw_s"].isin(["LONG", "SHORT"])]
    agree = float((fire["action_raw_y"] == fire["action_raw_s"]).mean())
    print(f"bars where either feed fires: {len(fire)}; same-action agreement = {agree:.3f} (>= 0.80)")
    ty, _ = run_proxy(Path(a.dec) / "SPY_proxy.csv", Path(a.inputs) / "SPY_1h_proxy.csv", "SPY")
    ts_, _ = run_proxy(Path(a.dec) / "SPY_sip_proxy.csv", Path(a.inputs) / "SPY_sip_1h_proxy.csv", "SPY")
    start = y.index[0].strftime("%Y-%m-%d")
    ty = [t for t in ty if start <= t.date <= end]
    ts_ = [t for t in ts_ if start <= t.date <= end]
    yrs = len(sessions_of(y)) / 252
    sy, ss = msh.trade_stats(ty, C2, yrs), msh.trade_stats(ts_, C2, yrs)
    print(fmt_stats("H_proxy Yahoo (C2)", sy))
    print(fmt_stats("H_proxy SIP   (C2)", ss))
    dm = sy["mean"] - ss["mean"]
    print(f"delta mean R = {dm:+.3f} (|.| <= 0.10)")
    ok = dclose.median() <= 2 and agree >= 0.80 and abs(dm) <= 0.10
    print(f"P0d (as pre-registered): {'PASS' if ok else 'FAIL'}")
    # Addendum A1 (pre-registration): the SIP bars are adjustment=all, the Yahoo bars are
    # dividend-unadjusted, so the raw close comparison measures the dividend back-adjustment,
    # not the feed. Adjustment-neutral re-measurement: divide out each session's median
    # Yahoo/SIP ratio (a multiplicative factor that only changes at ex-dividend dates).
    ratio = j["Close_y"] / j["Close_s"]
    day = msh._ny_dates(j.index)
    adj = ratio / ratio.groupby(day).transform("median")
    dnorm = float((adj - 1).abs().median() * 1e4)
    ok_amended = dnorm <= 2 and agree >= 0.80 and abs(dm) <= 0.10
    print(f"day-normalized median |dClose| = {dnorm:.2f} bps (<= 2) -> "
          f"P0d (Addendum A1, adjustment-neutral): {'PASS' if ok_amended else 'FAIL'}")
    return ok_amended


# ---------------------------------------------------------------------------
# Study
# ---------------------------------------------------------------------------


def stage_baseline(a, cache) -> None:
    hdr("B0 -- SPY 10-year baseline, H_live on SIP (2016-01-04..2026-08-12), live rule")
    live = cache.get("B0_live") or run_live_sip(a)
    sip = msh.load_bars(Path(a.inputs) / "SPY_sip_5m_rth.csv")
    yrs = len(sessions_of(sip)) / 252
    for side in ("both", "LONG", "SHORT"):
        tr = live if side == "both" else [t for t in live if t.side == side]
        for lab, c in COSTS:
            print(fmt_stats(f"SPY SIP {side} {lab}", msh.trade_stats(tr, c, yrs)))
    print(f"breakeven cost (both sides): {msh.breakeven_cost_bps(live):.2f} bps/side; "
          f"median stop = {np.median([t.stop_distance / t.entry_ref * 1e4 for t in live]):.1f} bps")
    # per-year (regime sensitivity)
    r = msh.r_at_cost(live, C2)
    yr = pd.Series(r, index=[t.date[:4] for t in live]).groupby(level=0).agg(["count", "mean", "sum"])
    print("per-year, both sides, C2:")
    print(yr.round(3).to_string())


def proxy_all(a, cache):
    if "proxy" in cache:
        return cache["proxy"]
    out = {}
    for sym in msh.ALL_SYMBOLS:
        tr, bars = run_proxy(Path(a.dec) / f"{sym}_proxy.csv", Path(a.inputs) / f"{sym}_1h_proxy.csv", sym)
        out[sym] = (tr, bars)
    cache["proxy"] = out
    return out


def stage_symbols(a, cache) -> Dict[str, str]:
    hdr("S1 -- per-symbol edge, H_proxy (Yahoo 1h, 2023-11-24..2026-10-21), live rule, both sides")
    px = proxy_all(a, cache)
    any_bars = px["SPY"][1]
    sess = sessions_of(any_bars)
    yrs = len(sess) / 252
    yrs_is = len([d for d in sess if d <= IS_END]) / 252
    yrs_oos = len([d for d in sess if d > IS_END]) / 252
    classes = {}
    ctrl_cache = {}
    print("-- full window, C2 (primary)")
    for sym in msh.ALL_SYMBOLS:
        tr, bars = px[sym]
        print(fmt_stats(sym, msh.trade_stats(tr, C2, yrs)))
    print("-- cost sensitivity: mean R at C0 / C2 / C3 / C1, breakeven bps/side, median stop bps")
    for sym in msh.ALL_SYMBOLS:
        tr, _ = px[sym]
        ms = [msh.r_at_cost(tr, c).mean() for _, c in COSTS]
        stop_bps = np.median([t.stop_distance / t.entry_ref * 1e4 for t in tr])
        print(f"{sym:<6s} C0={ms[0]:+.3f} C2={ms[1]:+.3f} C3={ms[2]:+.3f} C1={ms[3]:+.3f} "
              f"breakeven={msh.breakeven_cost_bps(tr):+6.2f} bps  stop={stop_bps:5.1f} bps")
    print("-- IS (<= 2025-04-30) vs OOS, C2")
    for sym in msh.ALL_SYMBOLS:
        tr, _ = px[sym]
        ti = [t for t in tr if t.date <= IS_END]
        to = [t for t in tr if t.date > IS_END]
        si, so = msh.trade_stats(ti, C2, yrs_is), msh.trade_stats(to, C2, yrs_oos)
        print(f"{sym:<6s} IS n={si['n']:4d} meanR={si['mean']:+.3f} [{si['ci_lo']:+.3f},{si['ci_hi']:+.3f}]   "
              f"OOS n={so['n']:4d} meanR={so['mean']:+.3f} [{so['ci_lo']:+.3f},{so['ci_hi']:+.3f}]")
    print("-- long vs short, and drift control (unconditional same-side entries), C2")
    for sym in msh.ALL_SYMBOLS:
        tr, bars = px[sym]
        parts = []
        upl_all = []
        for side in ("LONG", "SHORT"):
            ts = [t for t in tr if t.side == side]
            st = msh.trade_stats(ts, C2, yrs)
            rows = msh.control_outcomes(Path(a.dec) / f"{sym}_proxy.csv", bars, side)
            cr = msh.control_r(rows, C2)
            ctrl_cache[(sym, side)] = cr
            upl = st["mean"] - cr.mean()
            upl_all.append((len(ts), upl))
            parts.append(f"{side[0]}: n={st['n']:4d} R={st['mean']:+.3f} [{st['ci_lo']:+.3f},{st['ci_hi']:+.3f}] "
                         f"ctrl={cr.mean():+.3f} (n={len(cr)}) uplift={upl:+.3f}")
        print(f"{sym:<6s} " + " | ".join(parts))
        n_tot = sum(n for n, _ in upl_all)
        w_upl = sum(n * u for n, u in upl_all) / n_tot if n_tot else float("nan")
        full = msh.trade_stats(tr, C2, yrs)
        oos = msh.trade_stats([t for t in tr if t.date > IS_END], C2, yrs_oos)
        if full["ci_hi"] < 0:
            cls = "NEGATIVE"
        elif full["ci_lo"] > 0 and oos["mean"] > 0 and w_upl > 0:
            cls = "EDGE"
        else:
            cls = "NO_EDGE"
        classes[sym] = cls
    print("-- classification (pre-registered §6.1)")
    print("  " + ", ".join(f"{s}={c}" for s, c in classes.items()))
    cache["classes"] = classes
    return classes


def portfolio_daily(px, syms, frac_each, sessions, cost=C2):
    tot = pd.Series(0.0, index=pd.Index(sessions))
    for s in syms:
        tot = tot + msh.daily_pnl(px[s][0], cost, frac_each, sessions)
    return tot


def summarize_daily(label, d: pd.Series, n_trades: int, spy_r_frac: float):
    sh = d.mean() / d.std(ddof=1) * np.sqrt(252) if d.std(ddof=1) > 0 else float("nan")
    cum = d.cumsum()
    mdd = float((cum - cum.cummax()).min())
    print(f"{label:<44s} tr/day={n_trades/len(d):5.2f} mean={d.mean()*1e4:+6.3f} bp/day "
          f"Sharpe={sh:+5.2f} total={d.sum()*100:+7.2f}% maxDD={mdd*100:6.2f}% worst={d.min()*100:+6.3f}% "
          f"total_in_SPY_R={d.sum()/spy_r_frac:+8.1f}")
    return dict(mean=d.mean(), sharpe=sh, total=d.sum(), mdd=mdd)


def stage_portfolio(a, cache) -> None:
    hdr("S2 -- portfolio view, H_proxy, C2, non-compounding, fractions of equity")
    px = proxy_all(a, cache)
    sess = sessions_of(px["SPY"][1])
    spy_tr = px["SPY"][0]
    spy_r_frac = 0.10 * float(np.median([t.stop_distance / t.entry_ref for t in spy_tr]))
    print(f"SPY median 1R under V0 = {spy_r_frac*1e4:.2f} bp of equity = ${spy_r_frac*EQUITY:,.0f} at $1.02M")
    sets = (("A: SPY+top10", ("SPY",) + msh.TOP10, PRIORITY_TOP),
            ("B: SPY+ETFs", ("SPY",) + msh.ETFS, PRIORITY_ETF))
    v0 = portfolio_daily(px, ("SPY",), 0.10, sess)
    summarize_daily("V0 SPY only 10%", v0, len(spy_tr), spy_r_frac)
    cache["v0_daily"] = v0
    for name, syms, prio in sets:
        k = len(syms)
        ntr = sum(len(px[s][0]) for s in syms)
        v1 = portfolio_daily(px, syms, 0.10 / k, sess)
        summarize_daily(f"{name} V1 shared cap (10%/{k} each)", v1, ntr, spy_r_frac)
        cache[f"v1_{name[0]}"] = v1
        ev = {s: msh.events_from_proxy_emitter(Path(a.dec) / f"{s}_proxy.csv", s) for s in syms}
        bars = {s: px[s][1] for s in syms}
        single = msh.simulate(ev, bars, order="proxy", max_open=1, priority=prio)
        v1b = msh.daily_pnl(single, C2, 0.10, sess)
        summarize_daily(f"{name} V1b single slot 10%", v1b, len(single), spy_r_frac)
        r1b = msh.r_at_cost(single, C2)
        print(f"   V1b trades by symbol: {dict(Counter(t.sym for t in single))}; meanR={r1b.mean():+.3f}")
        v2 = portfolio_daily(px, syms, 0.10, sess)
        summarize_daily(f"{name} V2 per-symbol 10% (LARGER EXPOSURE)", v2, ntr, spy_r_frac)

    # correlation / N_eff on stand-alone books
    hdr("S2b -- risk spreading: daily P&L correlation, N_eff, return correlation, concurrency")
    for name, syms in (("A: SPY+top10", ("SPY",) + msh.TOP10), ("B: SPY+ETFs", ("SPY",) + msh.ETFS),
                       ("all 19", msh.ALL_SYMBOLS)):
        mat = pd.DataFrame({s: msh.daily_pnl(px[s][0], C2, 0.10, sess) for s in syms})
        c = mat.corr().to_numpy()
        iu = np.triu_indices(len(syms), 1)
        print(f"{name:<14s} K={len(syms):2d} avg pairwise corr={np.nanmean(c[iu]):+.3f} "
              f"N_eff(eigen)={msh.effective_n(np.nan_to_num(c)):.2f}")
        if name.startswith("A") or name.startswith("B"):
            print("   corr with SPY book: " + ", ".join(
                f"{s}={mat[s].corr(mat['SPY']):+.2f}" for s in syms if s != "SPY"))
    rets = {}
    for s in msh.ALL_SYMBOLS:
        b = px[s][1]
        d = msh._ny_dates(b.index)
        r = np.log(b["Close"]).diff()
        r[pd.Series(d, index=b.index) != pd.Series(d, index=b.index).shift()] = np.nan
        rets[s] = r
    R = pd.DataFrame(rets)
    print("1h close-to-close return corr with SPY: " + ", ".join(
        f"{s}={R[s].corr(R['SPY']):.2f}" for s in msh.ALL_SYMBOLS if s != "SPY"))
    for name, syms in (("A", ("SPY",) + msh.TOP10), ("B", ("SPY",) + msh.ETFS)):
        grid = px["SPY"][1].index.asi8 // 1_000_000
        open_cnt = np.zeros(len(grid), int)
        long_cnt = np.zeros(len(grid), int)
        for s in syms:
            for t in px[s][0]:
                m = (grid >= t.entry_ms) & (grid < max(t.exit_ms, t.entry_ms + 1))
                open_cnt[m] += 1
                if t.side == "LONG":
                    long_cnt[m] += 1
        multi = open_cnt >= 2
        same = ((long_cnt == open_cnt) | (long_cnt == 0)) & multi
        dist = Counter(open_cnt.tolist())
        print(f"concurrency {name}: share of bars with k open: " + ", ".join(
            f"{k}={v/len(grid)*100:.1f}%" for k, v in sorted(dist.items())) +
            f"; multi-position bars all same side = {same.sum()/max(multi.sum(),1)*100:.1f}%")


def stage_gate(a, cache) -> None:
    hdr("S3 -- overfitting gate (N=19 trials) and walk-forward selection")
    px = proxy_all(a, cache)
    sess = sessions_of(px["SPY"][1])
    mat = pd.DataFrame({s: msh.daily_pnl(px[s][0], C2, 0.10, sess) for s in msh.ALL_SYMBOLS})
    sharpes = (mat.mean() / mat.std(ddof=1)).to_numpy()
    best = mat.columns[int(np.argmax(sharpes))]
    print("daily Sharpe (non-annualized) per trial: " + ", ".join(
        f"{s}={v:+.3f}" for s, v in zip(mat.columns, sharpes)))
    v0 = cache["v0_daily"]
    month = pd.Index([d[:7] for d in sess])
    for key, label in (("v1_A", "A: SPY+top10 V1"), ("v1_B", "B: SPY+ETFs V1")):
        cand = cache[key]
        upl = (cand.groupby(month).sum() - v0.groupby(month).sum()).to_numpy()
        g = evaluate_gate(returns_best=mat[best].to_numpy(), all_trial_sharpes=sharpes,
                          perf_matrix=mat.to_numpy(), uplifts=upl, pbo_n_splits=16,
                          bootstrap_n_boot=2000, bootstrap_seed=0)
        print(f"{label}: best trial={best} DSR={g['dsr']:.4f} (sr_hat={g['dsr_result']['sr_hat']:+.4f}, "
              f"sr*={g['dsr_result']['sr_star']:.4f}) PBO={g['pbo']:.4f} "
              f"monthly uplift mean={upl.mean()*100:+.3f}% CI=[{g['bootstrap_result']['ci_low']*100:+.3f}%, "
              f"{g['bootstrap_result']['ci_high']*100:+.3f}%] -> passed={g['passed']} {g['reasons']}")

    # walk-forward
    for set_name, cands in (("top10", msh.TOP10), ("ETFs", msh.ETFS)):
        tot_sel, tot_v0, tot_all = 0.0, 0.0, 0.0
        for w, s0, s1 in WF_STEPS:
            tr_start = (pd.Timestamp(s0) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
            sel = ["SPY"]
            for s in cands:
                trs = [t for t in px[s][0] if tr_start <= t.date < s0]
                if trs and msh.r_at_cost(trs, C2).mean() > 0:
                    sel.append(s)
            wsess = [d for d in sess if s0 <= d <= s1]
            k = len(sel)
            sel_p = portfolio_daily(px, sel, 0.10 / k, wsess).sum()
            all_syms = ("SPY",) + tuple(cands)
            all_p = portfolio_daily(px, all_syms, 0.10 / len(all_syms), wsess).sum()
            v0_p = portfolio_daily(px, ("SPY",), 0.10, wsess).sum()
            tot_sel += sel_p
            tot_v0 += v0_p
            tot_all += all_p
            print(f"WF {set_name} {w} {s0}..{s1}: selected={sel} -> sel={sel_p*100:+.3f}% "
                  f"all-in V1={all_p*100:+.3f}% V0={v0_p*100:+.3f}%")
        print(f"WF {set_name} total OOS: selected={tot_sel*100:+.3f}% all-in={tot_all*100:+.3f}% "
              f"V0={tot_v0*100:+.3f}%  selected beats V0: {tot_sel > tot_v0}")


def stage_risks(a, cache) -> None:
    hdr("S4 -- single-stock-specific risks vs SPY")
    px = proxy_all(a, cache)
    raw = Path(a.raw)
    k = 11
    print(f"{'sym':<6s} {'stop_bps':>8s} {'1R$@10%':>8s} {'1R$@V1':>7s} {'hr_rng':>7s} "
          f"{'gap50':>6s} {'gap95':>6s} {'gap99':>6s} {'gapMax':>7s} {'gap>=5%/yr':>10s} {'SSR/yr':>6s} "
          f"{'$vol/hr(M)':>10s} {'ord%vol':>7s} {'evR':>6s} {'n_ev':>4s} {'othR':>6s} {'stopOvershootR':>14s}")
    for sym in msh.ALL_SYMBOLS:
        tr, bars = px[sym]
        stop_frac = np.median([t.stop_distance / t.entry_ref for t in tr])
        hr = ((bars["High"] - bars["Low"]) / bars["Open"]).median() * 1e4
        d = msh.load_bars(raw / f"{sym}_1d_yahoo.csv")
        d = d[d.index.strftime("%Y-%m-%d") <= "2026-10-21"]
        gap = (d["Open"] / d["Close"].shift() - 1).abs().dropna() * 1e4
        yrs_d = len(d) / 252
        ssr = int((d["Low"] <= 0.9 * d["Close"].shift()).sum())
        b1 = msh.load_bars(Path(a.inputs) / f"{sym}_1h_proxy.csv")
        full = b1[(b1.index.minute == 30)]
        rawv = pd.read_csv(raw / f"{sym}_1h_yahoo.csv")
        vol = pd.Series(rawv["Volume"].to_numpy(float), index=pd.to_datetime(rawv["timestamp"], utc=True))
        dv = (vol.reindex(full.index) * full["Close"]).median()
        order = 0.10 * EQUITY
        # event sessions: |gap| >= 3x median |gap| (5y daily)
        med_gap = gap.median()
        ev_days = set(gap[gap >= 3 * med_gap].index.strftime("%Y-%m-%d"))
        r = msh.r_at_cost(tr, C2)
        is_ev = np.array([t.date in ev_days for t in tr])
        evR = r[is_ev].mean() if is_ev.any() else float("nan")
        othR = r[~is_ev].mean()
        stops = [t for t in tr if t.reason == "stop"]
        over = []
        for t in stops:
            nominal = t.stop
            over.append(abs(t.exit_raw - nominal) / t.stop_distance)
        print(f"{sym:<6s} {stop_frac*1e4:8.1f} {0.10*EQUITY*stop_frac:8.0f} {0.10/k*EQUITY*stop_frac:7.0f} "
              f"{hr:7.1f} {gap.quantile(.5):6.1f} {gap.quantile(.95):6.1f} {gap.quantile(.99):6.1f} "
              f"{gap.max():7.1f} {(gap >= 500).sum()/yrs_d:10.2f} {ssr/yrs_d:6.2f} {dv/1e6:10.1f} "
              f"{order/dv*100:7.3f} {evR:+6.3f} {int(is_ev.sum()):4d} {othR:+6.3f} "
              f"{np.mean(over) if over else float('nan'):14.3f}")
    # buy-and-hold context (survivorship)
    print("buy-and-hold over the proxy window (first open -> last close):")
    print("  " + ", ".join(
        f"{s}={(px[s][1]['Close'].iloc[-1]/px[s][1]['Open'].iloc[0]-1)*100:+.0f}%" for s in msh.ALL_SYMBOLS))


def stage_concordance(a, cache) -> None:
    hdr("S5 -- 59-session concordance: H_live (Yahoo 5m, top-of-hour) vs H_proxy, same window")
    px = proxy_all(a, cache)
    for sym in msh.ALL_SYMBOLS:
        ev = msh.events_from_live_emitter(Path(a.dec) / f"{sym}_live60.csv", sym, mode="both")
        b5 = msh.load_bars(Path(a.inputs) / f"{sym}_5m.csv")
        lt = msh.simulate({sym: ev}, {sym: b5}, order="571")
        start = sessions_of(b5)[2]
        lt = [t for t in lt if t.date >= start]
        pt = [t for t in px[sym][0] if t.date >= start]
        rl, rp = msh.r_at_cost(lt, C2), msh.r_at_cost(pt, C2)
        print(f"{sym:<6s} H_live n={len(lt):3d} meanR={rl.mean() if len(rl) else float('nan'):+.3f} "
              f"cumR={rl.sum():+6.1f} | H_proxy n={len(pt):3d} meanR={rp.mean() if len(rp) else float('nan'):+.3f} "
              f"cumR={rp.sum():+6.1f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--dec", required=True)
    ap.add_argument("--sip-5m", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--stage", default="all",
                    choices=["p0b", "p0c", "p0d", "gates", "all"])
    a = ap.parse_args(argv)
    cache: dict = {}
    if a.stage in ("p0b", "gates", "all"):
        ok_b = stage_p0b(a)
    if a.stage == "p0b":
        return 0
    if a.stage in ("p0c", "gates", "all"):
        ok_c = stage_p0c(a, cache)
    if a.stage == "p0c":
        return 0
    if a.stage in ("p0d", "gates", "all"):
        ok_d = stage_p0d(a)
    if a.stage == "p0d":
        return 0
    if not (ok_b and ok_c and ok_d):
        print("\nA hard parity gate FAILED -- per the pre-registration §4/§7 the study stops here.")
        return 2
    if a.stage == "gates":
        return 0
    stage_baseline(a, cache)
    stage_symbols(a, cache)
    stage_portfolio(a, cache)
    stage_gate(a, cache)
    stage_risks(a, cache)
    stage_concordance(a, cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
