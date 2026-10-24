"""Parity gate P0: reproduce the published hourly-candlestick baseline B0 before using it.

Research-only. No network, no broker. Replays the UNCHANGED live rule's emitter output
(``scripts/emit_hourly_decisions.ts --shorts-enabled`` on the staged SPY SIP 60m bars, with
5Min fills) through the vendored multi-symbol simulator and checks it against the figures
published in ``2026-10-22-multi-symbol-hourly-verdict.md`` §3.1 (B0): n = 2,478,
234 trades/yr, mean R -0.031 at 0 bps/side and -0.139 at 1 bps/side.

Usage::

    CLAUDE_AGENT_NO_BROKER=1 venv/bin/python \
        docs/research/2026-10-22-spy-intraday-momentum-study/run_parity_b0.py \
        --decisions <scratch>/dec/SPY_sip_60m.csv --bars5 data/intraday/SPY_5min.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import vendored_multi_symbol_hourly as msh  # noqa: E402

PUBLISHED = {"n": 2478, "mean_c0": -0.031, "mean_c2": -0.139, "per_yr": 234}


def main(argv=None) -> int:
    assert os.environ.get("CLAUDE_AGENT_NO_BROKER") == "1", "export CLAUDE_AGENT_NO_BROKER=1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--bars5", required=True)
    a = ap.parse_args(argv)
    ev = msh.events_from_live_emitter(a.decisions, "SPY", mode="both")
    bars = msh.load_bars(a.bars5)
    trades = msh.simulate({"SPY": ev}, {"SPY": bars}, order="571")
    sessions = len(set(msh._ny_dates(msh.rth_only(bars).index)))
    yrs = sessions / 252
    s0 = msh.trade_stats(trades, 0.0, yrs)
    s2 = msh.trade_stats(trades, 1.0, yrs)
    print(f"sessions={sessions} years={yrs:.2f}")
    print(f"B0 C0: n={s0['n']} tr/yr={s0['per_yr']:.0f} meanR={s0['mean']:+.3f} "
          f"CI=[{s0['ci_lo']:+.3f},{s0['ci_hi']:+.3f}]")
    print(f"B0 C2: n={s2['n']} tr/yr={s2['per_yr']:.0f} meanR={s2['mean']:+.3f} "
          f"CI=[{s2['ci_lo']:+.3f},{s2['ci_hi']:+.3f}] win={s2['win']*100:.1f}%")
    ok = (s0["n"] == PUBLISHED["n"] and round(s0["mean"], 3) == PUBLISHED["mean_c0"]
          and round(s2["mean"], 3) == PUBLISHED["mean_c2"]
          and round(s2["per_yr"]) == PUBLISHED["per_yr"])
    print(f"P0 (B0 reproduces published figures exactly): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
