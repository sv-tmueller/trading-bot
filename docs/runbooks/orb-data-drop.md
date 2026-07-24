# Runbook: supplying intraday data for the ORB study

**Purpose:** run the long/short ORB study (#434) without any market-data network access.

The study's pre-registration is `docs/research/2026-07-24-orb-longshort-preregistration.md`;
its §6 explains why this runbook exists. Short version: every market-data host is denied by
the sandbox's egress policy, so the harness reads bars from a **local file** instead. Nothing
about the methodology changes — only the transport.

---

## 1. Export the bars

Any source works. The file needs one row per bar with a timestamp and OHLC.

Reasonable sources, cheapest first:

- Your Alpaca account's own data export, or a short script run **on your machine** (where
  egress is open) against `data.alpaca.markets`.
- Any broker/terminal export (IBKR, TradingView, etc.).
- A paid vendor (Databento, FirstRate) if you decide to fund full-power depth — see §6 of
  the pre-registration before spending, and note that #431 recommended against it.

**Depth is what determines whether you get a verdict:**

| Depth | Verdict class | What it can do |
|---|---|---|
| < 500 sessions | `UNDERPOWERED` | Nothing — the runner refuses to print cell numbers |
| ≥ 500 sessions, < 13 complete 12-month windows | `DIRECTIONAL` | Decides whether deeper data is worth funding |
| ≥ 13 windows | `PROMOTABLE` | Gate-eligible; can actually clear the bar |

## 2. Drop it in

```
data/intraday/SPY_5min.csv        # or .parquet / .pq / .csv.gz
```

`/data/` is gitignored, so nothing you put there is ever committed. The default lookup is
`data/intraday/<SYMBOL>_<timeframe>.<ext>` then `data/<SYMBOL>_<timeframe>.<ext>`; an
explicit `--data PATH` overrides both.

**Format.** Column names are matched case-insensitively, so all of these work:

- `Open/High/Low/Close`, `open/high/low/close`, or `o/h/l/c`
- Timestamp as the index, or a column named `timestamp` / `time` / `datetime` / `date` / `t`

The loader validates before simulating and **fails loudly** on NaNs, non-positive prices, or
bars whose High/Low do not bracket their own Open/Close (the signature of a mis-mapped
column). A loud failure here is the point — the alternative is confident nonsense downstream.

## 3. Run it

```bash
python3 -m backtest.run_orb_study --data data/intraday/SPY_5min.csv
```

Optional: `--symbol QQQ --timeframe 5Min` to change the default lookup.

Exit codes: **0** = a report was produced; **2** = DATA-BLOCKED (no usable data, or below the
directional-read floor). On exit 2 **no per-cell numbers are printed at all** — that is
deliberate, so shallow-sample output can never be mistaken for a read.

## 4. Record the result

If the run produces a report, paste it into §7 of
`docs/research/2026-07-24-orb-longshort-preregistration.md` **in a commit strictly later than
the one that froze §2–§5**, and do not edit those frozen sections. That ordering is what
makes the pre-registration checkable from git history.

---

## Alternative: allowlist the data host

Instead of a file, `data.alpaca.markets` can be added to the environment's network egress
settings, after which the read-only data keys work directly. That reaches ~n_w ≈ 9 (2016+)
— a `DIRECTIONAL` read, never gate-eligible. The local-file path is still preferred: it costs
nothing and depends on no one else.
