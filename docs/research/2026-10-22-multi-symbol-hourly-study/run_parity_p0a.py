"""Gate P0a: the study simulator must reproduce #571's published SPY 60m R=2.0 cell.

Research-only, no network, no broker. Input: the #571 staged SPY SIP bars and a decisions
CSV produced by the UNCHANGED ``scripts/emit_hourly_decisions.ts``. Expected (from
``docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md`` §3, cadence=60m
R=2.0): ``trades: 1805  expectancy(R): -0.5381``, exits ``flatten 1060 / target 147 /
stop 598``. Also cross-checks against ``backtest/hourly_geometry.simulate_hourly_geometry``
run in-process on the same inputs.

Usage::

    venv/bin/python docs/research/2026-10-22-multi-symbol-hourly-study/run_parity_p0a.py \
        --decisions <scratch>/dec/SPY_sip_60m.csv --bars5 data/intraday/SPY_5min.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import multi_symbol_hourly as msh  # noqa: E402
from backtest.hourly_geometry import (  # noqa: E402
    expectancy_r, exit_distribution, load_decisions_csv, simulate_hourly_geometry,
)
from backtest.intraday_data import load_local  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--bars5", required=True)
    a = ap.parse_args(argv)

    bars5 = load_local(a.bars5)
    ref = simulate_hourly_geometry(load_decisions_csv(a.decisions, 2.0), bars5, period_minutes=60)
    rt = ref["trades"]
    print(f"#571 module in-process: trades={len(rt)} expectancy(R)={expectancy_r(rt):.4f} "
          f"exits={exit_distribution(rt)}")

    ev = msh.events_from_live_emitter(a.decisions, "SPY", mode="parity571")
    bars = msh.load_bars(a.bars5)
    tr = msh.simulate({"SPY": ev}, {"SPY": bars}, order="571")
    r = msh.r_at_cost(tr, 5.0)
    print(f"study simulator:        trades={len(tr)} expectancy(R)={r.mean():.4f} "
          f"exits={dict(Counter(t.reason for t in tr))}")
    same = len(tr) == len(rt) and abs(r.mean() - expectancy_r(rt)) < 1e-9
    pub = len(tr) == 1805 and round(r.mean(), 4) == -0.5381
    print(f"matches #571 module trade-for-trade: {same}; matches published 1805/-0.5381: {pub}")
    return 0 if (same and pub) else 1


if __name__ == "__main__":
    raise SystemExit(main())
