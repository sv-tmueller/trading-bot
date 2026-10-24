"""P0d diagnostic: is the Yahoo-vs-SIP close gap a dividend-adjustment offset, not a feed gap?

The #571 SIP bars were staged with ``adjustment=all`` (dividend-adjusted back in time); the
Yahoo bars were fetched with ``auto_adjust=False``. A pure adjustment offset shows up as a
price ratio that is (i) constant within a session, (ii) steps only around SPY ex-dividend
dates (quarterly), and (iii) converges to 1.0 at the end of the SIP window. Bar SHAPE
(close/open, high/open, low/open) is unaffected by a multiplicative factor, so it measures
the feed difference alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import multi_symbol_hourly as msh  # noqa: E402


def main(inputs: str) -> int:
    y = msh.load_bars(Path(inputs) / "SPY_1h_proxy.csv")
    s = msh.load_bars(Path(inputs) / "SPY_sip_1h_proxy.csv")
    j = y.join(s, how="inner", lsuffix="_y", rsuffix="_s")
    ratio = j["Close_y"] / j["Close_s"]
    day = pd.Series(msh._ny_dates(j.index), index=j.index)
    per_day = ratio.groupby(day.to_numpy())
    within = per_day.agg(lambda r: (r.max() / r.min() - 1) * 1e4)
    med_ratio = per_day.median()
    steps = med_ratio[(med_ratio.pct_change().abs() * 1e4) > 5]
    print(f"ratio Yahoo/SIP: first day {med_ratio.iloc[0]:.5f}, last day {med_ratio.iloc[-1]:.5f}")
    print(f"within-session ratio spread: median {within.median():.2f} bps, p95 {within.quantile(.95):.2f} bps")
    print(f"days where the per-day median ratio steps by > 5 bps: {len(steps)} -> {list(steps.index)}")
    adj = ratio / ratio.groupby(day.to_numpy()).transform("median")
    print(f"day-normalized |dClose|: median {(adj - 1).abs().median() * 1e4:.2f} bps, "
          f"p95 {(adj - 1).abs().quantile(.95) * 1e4:.2f} bps")
    for col in ("Close", "High", "Low"):
        dy = j[f"{col}_y"] / j["Open_y"] - 1
        ds = j[f"{col}_s"] / j["Open_s"] - 1
        d = (dy - ds).abs() * 1e4
        print(f"bar shape |d({col}/Open)|: median {d.median():.2f} bps, p95 {d.quantile(.95):.2f} bps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
