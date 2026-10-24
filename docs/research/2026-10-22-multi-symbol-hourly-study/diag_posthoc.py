"""Post-hoc diagnostics (NOT pre-registered; labelled as such in the verdict doc).

1. V1b single-slot: block-bootstrap CI on mean daily P&L, t-stat, and the V1b trade ledger
   re-priced with the P0c construction offset (H_proxy runs ~+0.085R optimistic vs H_live on
   SPY SIP) to show how much of V1b's sign survives the known harness bias.
2. Drift-control sanity: rule-minus-control uplift at C0, and with the control restricted to
   bars whose stop distance (bps of price) lies inside the rule trades' inter-quartile range --
   tests whether the uplift is a stop-width artefact rather than selection skill.
3. Survivorship size: average holding time and the per-trade drift contribution implied by
   each symbol's buy-and-hold log return over the window, in R units.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import multi_symbol_hourly as msh  # noqa: E402
from backtest.overfitting_gate import block_bootstrap_ci  # noqa: E402

C0, C2 = 0.0, 1.0


def main(inputs: str, dec: str) -> int:
    inputs_p, dec_p = Path(inputs), Path(dec)
    px = {}
    for s in msh.ALL_SYMBOLS:
        ev = msh.events_from_proxy_emitter(dec_p / f"{s}_proxy.csv", s)
        b = msh.load_bars(inputs_p / f"{s}_1h_proxy.csv")
        px[s] = (ev, b, msh.simulate({s: ev}, {s: b}, order="proxy"))
    sess = sorted(set(msh._ny_dates(px["SPY"][1].index)))

    print("== 1. V1b single slot (priority SPY, then SSGA weight order)")
    for name, syms in (("A", ("SPY",) + msh.TOP10), ("B", ("SPY",) + msh.ETFS)):
        single = msh.simulate({s: px[s][0] for s in syms}, {s: px[s][1] for s in syms},
                              order="proxy", max_open=1, priority=syms)
        d = msh.daily_pnl(single, C2, 0.10, sess)
        ci = block_bootstrap_ci(d.to_numpy(), n_boot=2000, seed=0)
        t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
        r = msh.r_at_cost(single, C2)
        # P0c offset applied in R, converted to equity via each trade's stop fraction
        stop_frac = np.array([tr.stop_distance / tr.entry_raw for tr in single])
        shifted = (r - 0.085) * stop_frac * 0.10
        dshift = pd.Series(shifted, index=[tr.date for tr in single]).groupby(level=0).sum()
        print(f"{name}: n={len(single)} meanR={r.mean():+.3f} mean daily={d.mean()*1e4:+.3f} bp "
              f"CI=[{ci['ci_low']*1e4:+.3f},{ci['ci_high']*1e4:+.3f}] bp t={t:+.2f} total={d.sum()*100:+.2f}% "
              f"| with -0.085R P0c offset: total={dshift.sum()*100:+.2f}%")
        by = pd.DataFrame({"sym": [tr.sym for tr in single], "r": r,
                           "pnl": msh.ret_on_notional(single, C2) * 0.10})
        print("   by symbol (n, meanR, total % equity): " + ", ".join(
            f"{s}=({g.r.size},{g.r.mean():+.2f},{g.pnl.sum()*100:+.2f}%)" for s, g in by.groupby("sym")))

    print("== 2. drift-control uplift: C0, and stop-width-matched control (rule IQR of stop bps)")
    for s in msh.ALL_SYMBOLS:
        tr, b = px[s][2], px[s][1]
        out = []
        for side in ("LONG", "SHORT"):
            ts = [t for t in tr if t.side == side]
            rows = msh.control_outcomes(dec_p / f"{s}_proxy.csv", b, side)
            rule_bps = np.array([t.stop_distance / t.entry_raw * 1e4 for t in ts])
            lo, hi = np.percentile(rule_bps, [25, 75])
            cb = rows[:, 2] / rows[:, 0] * 1e4
            m = (cb >= lo) & (cb <= hi)
            u0 = msh.r_at_cost(ts, C0).mean() - msh.control_r(rows, C0).mean()
            u2m = msh.r_at_cost(ts, C2).mean() - msh.control_r(rows[m], C2).mean()
            ctrl_med = np.median(cb)
            out.append(f"{side[0]} uplift C0={u0:+.3f} matched C2={u2m:+.3f} "
                       f"(rule stop med {np.median(rule_bps):.0f} bps vs ctrl {ctrl_med:.0f})")
        print(f"{s:<6s} " + " | ".join(out))

    print("== 3. holding time and implied drift per long trade (R units)")
    for s in msh.ALL_SYMBOLS:
        tr, b = px[s][2], px[s][1]
        hold_h = np.mean([(t.exit_ms - t.entry_ms) / 3.6e6 for t in tr])
        bh = b["Close"].iloc[-1] / b["Open"].iloc[0]
        per_hour = np.log(bh) / (len(sess) * 6.5)
        stop = np.median([t.stop_distance / t.entry_raw for t in tr])
        drift_r = per_hour * max(hold_h, 1e-9) / stop
        print(f"{s:<6s} hold={hold_h:4.2f}h B&H={bh-1:+6.0%} drift per long trade ~ {drift_r:+.3f}R "
              f"(short: {-drift_r:+.3f}R)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
