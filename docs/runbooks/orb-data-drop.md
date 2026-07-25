# Runbook: supplying price data for the ORB and candlestick studies

**Purpose:** run the long/short ORB study (#434) or the daily candlestick-pattern study
without any market-data network access.

Two studies read bars this way. They need **different data**, so check which one you are
feeding:

| Study | Bars needed | Runner | Pre-registration |
|---|---|---|---|
| Long/short ORB | **intraday** (5-min), 2016+ | `backtest.run_orb_study` | `docs/research/2026-07-24-orb-longshort-preregistration.md` |
| Candlestick patterns | **daily**, 1993+ | `backtest.run_candlestick_study` | `docs/research/2026-07-25-candlestick-pattern-preregistration.md` |

The daily study is the easier one to satisfy: daily SPY history is small, freely exportable
almost anywhere, and reaches `PROMOTABLE` power (~33 windows) — whereas free intraday tops
out at a `DIRECTIONAL` read. **If you are only going to export one file, export daily SPY.**

Everything below applies to both unless a step says otherwise.

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

**Intraday / ORB:**

```bash
python3 -m backtest.run_orb_study --data data/intraday/SPY_5min.csv
```

Optional: `--symbol QQQ --timeframe 5Min` to change the default lookup.

**Daily / candlestick patterns:**

```bash
python3 -m backtest.run_candlestick_study --data data/SPY_daily.csv
```

Optional: `--vehicle ES=F` for the disclosed secondary robustness arm, `--end YYYY-MM-DD`
to pin the last date.

Exit codes (both runners): **0** = a report was produced; **2** = DATA-BLOCKED (no usable
data, or below the power floor). On exit 2 **no per-cell numbers are printed at all** — that
is deliberate, so shallow-sample output can never be mistaken for a read.

## 4. Record the result

If the run produces a report, paste it into **§7 of that study's pre-registration** (see the
table at the top for which file) **in a commit strictly later than the one that froze the
earlier sections**, and do not edit those frozen sections. That ordering is what makes the
pre-registration checkable from git history.

Report every cell, including `no-trades` and `RUINED` ones. The runners print those counts
for exactly this reason — a truncated table reads as "covered everything" when it did not.

---

## Alternative: allowlist the data host

Instead of a file, `data.alpaca.markets` can be added to the environment's network egress
settings, after which the read-only data keys work directly. For the **intraday** study that
reaches ~n_w ≈ 9 (2016+) — a `DIRECTIONAL` read, never gate-eligible. For the **daily**
study, allowlisting Yahoo (`query1.finance.yahoo.com`, `fc.yahoo.com`) is enough for the
runner's built-in fetch to reach 1993+ and clear `PROMOTABLE`.

The local-file path is still preferred: it costs nothing and depends on no one else.
