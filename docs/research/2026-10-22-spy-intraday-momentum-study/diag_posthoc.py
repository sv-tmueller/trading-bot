"""POST-HOC diagnostics for the SPY intraday momentum study (NOT pre-registered).

Research-only, local files only, no network, no broker. Nothing here can change the verdict;
these checks only test how fragile the pre-registered numbers are and whether the data
pipeline is internally consistent. Labelled post-hoc in the verdict doc.

1. The three 2020-03 circuit-breaker sessions (first-run deviation, see verdict): their r1,
   r13 and V1-E1 gross return, and b1 with/without them.
2. b1 with the top 1% of |r1| sessions trimmed.
3. Internal consistency: r1 and r13 rebuilt from the separately staged SPY_30min.csv.
4. r12-sign-only rule (one significant sub-sample cell in §2): gross and 1 bp/side, full
   sample and 2021+, to size the forking path honestly.

Usage::

    CLAUDE_AGENT_NO_BROKER=1 venv/bin/python \
        docs/research/2026-10-22-spy-intraday-momentum-study/diag_posthoc.py \
        --bars5 data/intraday/SPY_5min.csv --bars30 data/intraday/SPY_30min.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

import run_momentum_study as ms  # noqa: E402
from backtest.intraday_data import load_local  # noqa: E402
from backtest.overfitting_gate import block_bootstrap_ci  # noqa: E402

CB_DAYS = ["2020-03-09", "2020-03-12", "2020-03-16"]


def main(argv=None) -> int:
    assert os.environ.get("CLAUDE_AGENT_NO_BROKER") == "1", "export CLAUDE_AGENT_NO_BROKER=1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars5", required=True)
    ap.add_argument("--bars30", required=True)
    a = ap.parse_args(argv)
    s_all = ms.build_sessions(load_local(a.bars5))
    s = s_all[s_all["eligible"]]

    print("1. circuit-breaker sessions")
    for d in CB_DAYS:
        r = s.loc[d]
        g = np.sign(r["r1"]) * (r["X_mkt"] / r["E_in"] - 1) * 1e4
        print(f"  {d}: r1={r['r1']*1e4:+.0f}bps r12={r['r12']*1e4:+.0f}bps r13={r['r13']*1e4:+.0f}bps "
              f"V1-E1 gross={g:+.0f}bps RV1={'undefined' if np.isnan(r['RV1']) else round(r['RV1'], 4)}")
    full = ms.reg(s, ["r1"])
    wo = ms.reg(s.drop(index=CB_DAYS), ["r1"])
    print(f"  b1 full={full['beta'][1]:+.4f} (t {full['t'][1]:+.2f}); without the 3 days="
          f"{wo['beta'][1]:+.4f} (t {wo['t'][1]:+.2f})")
    t_all = ms.trades_for(s, "V1", "E1")
    t_wo = ms.trades_for(s.drop(index=CB_DAYS), "V1", "E1")
    print(f"  V1-E1 gross mean: all={ms.net_ret(t_all, 0).mean()*1e4:+.2f}bps "
          f"without the 3 days={ms.net_ret(t_wo, 0).mean()*1e4:+.2f}bps")

    print("2. trim top 1% |r1|")
    cut = s["r1"].abs().quantile(0.99)
    tr = s[s["r1"].abs() <= cut]
    r = ms.reg(tr, ["r1"])
    print(f"  |r1| cut={cut*1e4:.0f}bps n={r['n']} b1={r['beta'][1]:+.4f} t={r['t'][1]:+.2f} "
          f"R2={r['r2']*100:.2f}%")

    print("3. internal consistency vs SPY_30min.csv")
    b30 = load_local(a.bars30)
    loc = b30.index.tz_convert(ms.NY)
    df = b30.copy()
    df["d"] = loc.strftime("%Y-%m-%d")
    df["m"] = loc.hour * 60 + loc.minute
    C = df.pivot_table(index="d", columns="m", values="Close", aggfunc="first")
    days = list(s_all.index)
    C = C.reindex(days)
    close30 = np.where(s_all["half"], C[750], C[930])  # 12:30 / 15:30 bars close at 13:00 / 16:00
    alt = pd.DataFrame(index=days)
    alt["C_prev"] = pd.Series(close30, index=days).shift(1)
    alt["r1"] = C[570] / alt["C_prev"] - 1      # 09:30 bar close = price at 10:00
    alt["r13"] = C[930] / C[900] - 1            # 15:30 bar close / 15:00 bar close
    j = s[["r1", "r13"]].join(alt.add_suffix("_30"), how="inner").dropna()
    for c in ("r1", "r13"):
        d = (j[c] - j[f"{c}_30"]).abs() * 1e4
        print(f"  {c}: n={len(j)} median |diff|={d.median():.3f}bps p99={d.quantile(.99):.3f}bps "
              f"max={d.max():.3f}bps sign agreement={(np.sign(j[c]) == np.sign(j[c + '_30'])).mean():.4f}")

    print("4. r12-sign-only rule (POST-HOC forking path; not a candidate)")
    for lab, sub in (("full", s), ("2021+", s[s.index > ms.IS_END]), ("2016-2020", s[s.index <= ms.IS_END])):
        sg = np.sign(sub["r12"])
        t = pd.DataFrame({"sign": sg, "E": sub["E_in"], "X": sub["X_mkt"]})
        t = t[t["sign"] != 0]
        for cost in (0.0, 1.0):
            bps = ms.net_ret(t, cost).to_numpy() * 1e4
            ci = block_bootstrap_ci(bps, n_boot=2000, seed=0)
            print(f"  {lab:<10s} @{cost}: n={len(bps)} mean={bps.mean():+.2f}bps "
                  f"[{ci['ci_low']:+.2f},{ci['ci_high']:+.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
