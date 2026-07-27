# Runbook: supplying 1h EUR/USD data for the Elliott Wave research leg

**Purpose:** run `backtest.run_fx_ew_calibration` (#468) without depending on the FXCM
fetch path, and document the (documented-only, not-built) depth extension beyond FXCM's
own history.

This runbook is for the **forex 1h Elliott Wave** package specifically. It cross-links
[`docs/runbooks/orb-data-drop.md`](orb-data-drop.md), which is titled for the ORB and daily
candlestick studies and should not be overloaded with FX-specific vendor detail.

---

## 1. The default path needs no runbook at all

Unlike the ORB/candlestick studies, this package's primary data source
(`backtest/fx_data.py`'s FXCM H1 EUR/USD archive) was **reachable** in the session that
built this package (`fx_data.get_week_bytes(2023, 5, fetch=True)` succeeded; see
`docs/research/2026-07-27-forex-1h-data-feasibility.md` §2.2). If your environment can also
reach `candledata.fxcorporate.com`, just run:

```bash
python3 -m backtest.run_fx_ew_calibration --fetch
```

This downloads any missing weekly files into the gitignored `data/fxcm/H1/EURUSD/` cache
and prints the full calibration report. Nothing below is needed in that case.

## 2. The `--data PATH` contract (when FXCM itself is blocked)

If `candledata.fxcorporate.com` is egress-denied in your environment, drop a 1h EUR/USD
OHLC file in and point the runner at it directly — no network at all:

```bash
python3 -m backtest.run_fx_ew_calibration --data data/eurusd_1h.csv
```

Format, matching `intraday_data.load_local`'s accepted spellings (case-insensitive):

- `Open/High/Low/Close`, `open/high/low/close`, or `o/h/l/c`
- Timestamp as the index, or a column named `timestamp` / `time` / `datetime` / `date` / `t`
- CSV, CSV.GZ, or Parquet (`.csv`, `.csv.gz`, `.parquet`, `.pq`)

The loader validates before reporting and fails loudly (`DATA-BLOCKED`, exit 2) on NaNs,
non-positive prices, or bars whose High/Low do not bracket their own Open/Close — the
signature of a mis-mapped column. A loud failure here is the point.

`/data/` is gitignored (`.gitignore`) — **nothing dropped there is ever committed**, and
`git ls-files data/` must stay empty. This matters doubly here: histdata.com's own ToS
restricts redistribution of its exports (§4 below), so a local-only drop is not just
convention, it is the only compliant way to use that source at all.

## 3. Depth → verdict table

Reused from `docs/research/2026-07-27-forex-1h-data-feasibility.md` §2.5 (the frozen power
floors, `backtest/intraday_data.py`):

| Depth | Verdict class | What it can do |
|---|---|---|
| < 500 sessions | `UNDERPOWERED` | Nothing — firing-rate calibration still runs (it is exempt from the power gate), but no performance grid would ever be gate-eligible on this frame |
| ≥ 500 sessions, < 13 complete 12-month windows | `DIRECTIONAL` | Decides whether deeper data is worth funding; not gate-eligible |
| ≥ 13 windows | `PROMOTABLE` | Gate-eligible; a frozen pre-registration could actually clear the bar |

FXCM H1 alone (2012 week 1 → present) already reaches **`PROMOTABLE`** (n_w ≈ 14) — see the
feasibility note. Nothing below buys a *verdict class* FXCM doesn't already have; it only
buys *depth* (more non-overlapping windows, useful for a future, larger grid or a
robustness check on an earlier era).

## 4. Depth extension: two vendors, documented only, NOT implemented

**Recommendation: neither is built in this package** (batch #464 D3 / SUB_PLAN §2.3,
lever L1) — FXCM H1 is the mandatory and only implemented source this batch. Building
either of the below is a new vendor integration plus its own timezone/validation gate —
a size:M package on its own. Both entries below are reported **[to verify at fetch
time]**: the specifics are from model knowledge, not a fetched-and-dated observation, and
this repo's convention is a live URL plus a fetch date, or an explicit `[unverified]` tag.

### histdata.com — free M1, ~2000/2001+

**[to verify at fetch time]** Free minute-bar (M1) exports, per-pair per-month ZIPs, back
to roughly 2000-2001 for major pairs. No credentials needed, but the download path is a
form-token POST behind a `Referer` check (deliberately anti-bot) rather than a plain GET —
scriptable, but needs a small session-handling shim, not a bare `requests.get`. Getting one
pair over ~25 years is on the order of 300 monthly requests.

Two real gotchas, named so nobody rediscovers them the hard way:

- **Needs M1 → H1 resampling** — a second aggregation step this package's H1-native FXCM
  path doesn't need at all.
- **Timestamps are commonly documented as EST, without a DST adjustment** — a materially
  different convention from FXCM's H1 archive, which is already UTC
  (`backtest/fx_data.py`'s module docstring). This is exactly the class of bug
  `fx_data.check_weekend_bars` exists to catch (see the +4h/+5h incident that check was
  added for) — any histdata.com integration MUST re-derive and test its own timezone
  handling from scratch, never assume FXCM's.
- **Redistribution is ToS-restricted** — reinforces §2 above: a histdata.com export must
  stay in the gitignored `data/` directory, never committed, ever.

### Dukascopy — free tick data, ~2003+

**[to verify at fetch time]** Free tick-level data from roughly 2003, at
`datafeed.dukascopy.com/datafeed/EURUSD/YYYY/MM/DD/HHh_ticks.bi5` — no credentials, fully
scriptable. Two gotchas:

- **Tick-level, not bars** — needs a tick → H1 aggregation step, which is its own
  validation surface (in addition to timezone handling), and the file count is much
  higher (thousands of files per year rather than FXCM's 52-53 weekly files).
  - Format is LZMA-compressed binary (`.bi5`), point-scaled integers — a third parsing
    surface beyond FXCM's plain gzip CSV.
- **0-based month index** — a well-known footgun (`MM` in the URL path is 0-11, not 1-12).

### What depth either would buy

Extending back to ~2000-2003 (either vendor) would raise `n_w` from FXCM's ~14 to roughly
**~23** — more non-overlapping windows for a deeper robustness check, not a change in
verdict *class* (FXCM H1 alone is already `PROMOTABLE`). Fund this only if a later, frozen
Elliott Wave read ever justifies the extra vendor-integration cost — see
`docs/research/2026-07-27-forex-1h-data-feasibility.md` §7 for the open item.

## 5. Record the result

If you run the calibration against a locally-supplied file, paste the report into the
feasibility note or a dated follow-up — never into the DRAFT pre-registration's frozen
sections (there are none yet; see that document's banner).
