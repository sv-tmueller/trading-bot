"""Run both decision emitters over every prepared input (subprocess -> deno, file-in/file-out).

Research-only. Requires ``CLAUDE_AGENT_NO_BROKER=1`` in the environment (asserted). Writes
decision CSVs into ``--out-dir``:

* ``<SYM>_proxy.csv``      ``emit_proxy_decisions.ts`` on ``<SYM>_1h_proxy.csv`` (H_proxy)
* ``SPY_sip_proxy.csv``    same, on the SIP-derived :30 grid (gate P0c/P0d)
* ``<SYM>_live60.csv``     UNCHANGED ``scripts/emit_hourly_decisions.ts --shorts-enabled`` on
                           ``<SYM>_60m_from5m.csv`` with ``--bars5 <SYM>_5m.csv`` (H_live, 59 sessions)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import multi_symbol_hourly as msh  # noqa: E402


def _deno(args, scratch: Path) -> None:
    cmd = ["deno", "run", "--allow-env", "--allow-read", f"--allow-write={scratch}"] + args
    subprocess.run(cmd, cwd=REPO, check=True, stdout=subprocess.DEVNULL)


def main(argv=None) -> int:
    assert os.environ.get("CLAUDE_AGENT_NO_BROKER") == "1", "export CLAUDE_AGENT_NO_BROKER=1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    inp, out = Path(a.inputs), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    proxy = str(HERE / "emit_proxy_decisions.ts")
    live = str(REPO / "scripts" / "emit_hourly_decisions.ts")
    for sym in msh.ALL_SYMBOLS:
        _deno([proxy, "--bars", str(inp / f"{sym}_1h_proxy.csv"),
               "--out", str(out / f"{sym}_proxy.csv")], out)
        _deno([live, "--bars", str(inp / f"{sym}_60m_from5m.csv"),
               "--bars5", str(inp / f"{sym}_5m.csv"), "--out", str(out / f"{sym}_live60.csv"),
               "--period-minutes", "60", "--shorts-enabled"], out)
        print(f"{sym}: done")
    _deno([proxy, "--bars", str(inp / "SPY_sip_1h_proxy.csv"),
           "--out", str(out / "SPY_sip_proxy.csv")], out)
    print("SPY_sip_proxy: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
