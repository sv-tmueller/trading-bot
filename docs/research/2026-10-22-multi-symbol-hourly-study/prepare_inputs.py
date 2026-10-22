"""Turn the raw Yahoo downloads (and #571's staged SPY SIP 5Min bars) into harness inputs.

Research-only, local files only. Writes into ``--out-dir`` (scratch, never committed):

* ``<SYM>_1h_proxy.csv``      Yahoo 1h, RTH, 4-dp rounded, NY session date <= --end-date
* ``<SYM>_5m.csv``            Yahoo 5m, same treatment (last ~60 sessions only)
* ``<SYM>_60m_from5m.csv``    top-of-hour 60m bars resampled from the Yahoo 5m frame
* ``SPY_sip_5m_rth.csv``      #571's SIP 5Min bars, RTH only
* ``SPY_sip_1h_proxy.csv``    SIP 5Min resampled onto Yahoo's :30 grid (gate P0c/P0d)

Prints row counts, session counts and SHA256 per file (cited in the pre-registration §2).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import multi_symbol_hourly as msh  # noqa: E402


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sip-5m", required=True, help="#571's staged data/intraday/SPY_5min.csv")
    ap.add_argument("--end-date", default="2026-10-21")
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    msh.prepare_inputs(Path(a.raw_dir), out, a.end_date, msh.ALL_SYMBOLS)

    sip = msh.rth_only(msh.load_bars(a.sip_5m))
    msh._write_bars(sip, out / "SPY_sip_5m_rth.csv")
    msh._write_bars(msh.resample_half_hour_grid(sip), out / "SPY_sip_1h_proxy.csv")

    for p in sorted(out.glob("*.csv")):
        df = msh.load_bars(p)
        sess = len(set(msh._ny_dates(df.index)))
        print(f"{p.name:28s} rows={len(df):7d} sessions={sess:5d} "
              f"{df.index[0]} -> {df.index[-1]} sha256={_sha(p)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
