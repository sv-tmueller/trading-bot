# Bracket-geometry, cadence, and sizing study on SPY intraday bars — data feasibility gate (#566)

**Issue:** #566 (part of batch #565). **Design authority:** the SUB_PLAN comment on #566.
**Predecessors:** `docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md` (measured
SPY 5Min SIP reaching 2016, n_w≈9), `backtest/intraday_data.py` (#434 — the power floors and
local drop-in convention this gate uses verbatim), `backtest/run_orb_probe.py` /
`docs/research/2026-07-24-orb-probe-verdict.md` (the DATA-BLOCKED reporting shape this doc
mirrors). **Date:** 2026-08-13. **Author:** Claude Code session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` implicit — no broker order call anywhere in this package; the only
network touched anywhere in this session is read-only `GET /v2/stocks/SPY/bars` and, for the
disclosed fallback check, Yahoo Finance's public quote endpoint via `yfinance`).

---

## §0 Invariant framing

This package lives entirely under `backtest/`, `tests/`, and `docs/research/` — the offline
research path (`docs/architecture/2026-07-05-codebase-map.md`). It adds no live/TypeScript code
under `supabase/functions/`, no new decision rule, and reaches no broker order endpoint. It does
not change `.env.example` or any README config table. Nothing here authorizes anything live —
this doc measures whether SPY intraday history is available in this environment/session and
reports the honest result, whatever it turns out to be.

## §1 What this study would have run (frozen design, recorded for the next attempt)

Per the SUB_PLAN, the study is a **6-cell primary grid**: `R ∈ {1.0, 1.5, 2.0} × cadence ∈
{60m, 30m}`, replaying `decideHourly` + `computeBracketGeometry` + `computeSizing`
(`supabase/functions/_shared/hourly_signal.ts` / `hourly-check/logic.ts`) against SPY SIP bars
from 2016-01-01, with entry/flatten fills on the next 5Min bar's open, `_resolve_bar`
(`backtest/bracket.py`) exit resolution (STOP-first tie-break), a sizing-cap replay at
`{0.10, 0.25, 0.50, 1.00}` (a sizing-invariant replay of the same 6 ledgers, so registered
trials = 6, per #499's method), and a disclosed IEX-vs-SIP decision-concordance check on the
overlapping window. Every simulation convention (scan+7min cadence, flatten-window mapping,
STOP-first tie-break, cooldown/day-cap/geometry gates, `HOURLY_SHORTS_ENABLED=false` modeled
by assumption) is exactly as pre-registered in the SUB_PLAN's Q3 — restated here only as the
frozen target for whoever re-runs this once data is available; **none of it is executed or
scored in this package.**

**Fidelity correction to the SUB_PLAN text (disclosed, not silently followed):** the SUB_PLAN's
Q1 says to "recommend raw [bars] — matches what the live bot sees." That has it backwards: the
live `hourly-check` bot's `marketdata.getHourlyBars` fetches with `adjustment=all`
(`supabase/functions/_shared/marketdata.ts`, #265's rationale), i.e. **fully split/dividend
adjusted**, not raw. `backtest/run_fetch_spy_intraday.py` (built in this package, §2.4) defaults
to `adjustment="all"` to match live fidelity, with `adjustment` left as a parameter so a future
run can compare both. Whoever picks this study back up should use `adjustment="all"` as the
primary series and treat "raw" as the disclosed alternate, not the reverse.

## §2 Data feasibility gate — result: DATA-BLOCKED

### §2.1 Alpaca (primary source, SUB_PLAN Q1)

No `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (the Python-side names,
`options_data.RealAlpacaSource`'s and `run_orb_probe._fetch_alpaca`'s convention) or
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` (the current TS-side names, `config.ts`'s convention) are
set in this environment — confirmed via `os.environ` inspection and via
`backtest.run_fetch_spy_intraday.resolve_keys()`, which is the exact lookup the fetch helper
uses. No `.env` / `.env.backfill` file exists in the worktree either (only the gitignored
`.env.backfill.example` template).

**Egress vs. key-gating, distinguished** (the #431/#434 precedent's distinction, re-run here):
a direct unauthenticated GET reaches the host and returns HTTP 401, not a timeout/DNS failure —

```
$ curl -sS -m 8 -o /dev/null -w "%{http_code}\n" \
    "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day&limit=1"
401
```

and the fetch helper's own network path, exercised with placeholder credentials (never a real
key), reproduces the same result end-to-end:

```python
>>> import backtest.run_fetch_spy_intraday as f
>>> f.fetch_bars('SPY', '60Min', '2016-01-01', '2016-01-10', key='bogus', secret='bogus')
HTTPError: HTTP Error 401: Unauthorized
```

So this environment's egress is **open** to `data.alpaca.markets` (unlike the #434 precedent,
where every market-data host was 403-denied) — the blocker here is specifically **no data keys
available**, which is the same practical DATA-BLOCKED outcome the SUB_PLAN's stop condition
covers ("if neither fetch nor operator drop-in materializes").

The CLI itself, run for real with no keys set:

```
$ venv/bin/python -m backtest.run_fetch_spy_intraday --out-dir <scratch>
SPY 60Min: source=none rows=0 — DATA_BLOCKED: Alpaca data keys not set (...)
SPY 30Min: source=none rows=0 — DATA_BLOCKED: Alpaca data keys not set (...)
SPY 5Min: source=none rows=0 — DATA_BLOCKED: Alpaca data keys not set (...)
$ echo $?
3
```

(`3` = all three requested timeframes blocked — the CLI's designed return value, §2.4.)

### §2.2 Local drop-in (SUB_PLAN Q1's designed workaround)

`resolve_intraday()`'s conventional search dirs (`data/intraday/`, `data/`) do not exist in this
worktree at all — no operator drop-in file (`SPY_60min.csv`/`SPY_30min.csv`/parquet
equivalents) is present. Per the issue's own instruction, this package does **not** stall
waiting for an operator to supply one — it reports DATA-BLOCKED now.

### §2.3 yfinance (fallback-only, tried for completeness, disclosed not selected)

The SUB_PLAN already states yfinance is fallback-only and cannot serve the 30-min arm (#422 on
record). Re-verified live in this session rather than merely cited:

| Cadence | `yfinance` call | Rows | Span | `describe_power` verdict |
|---|---|---|---|---|
| 60Min | `download("SPY", period="730d", interval="60m")` | 5,082 | 2023-09-14 → 2026-08-12 | `DIRECTIONAL: 730 sessions, n_w=2` |
| 30Min | `download("SPY", period="60d", interval="30m")` | 780 | 2026-05-18 → 2026-08-12 | `UNDERPOWERED: 60 sessions, n_w=0` — below the 500-session directional floor |

This confirms #422's on-record finding exactly: yfinance's intraday depth cap (≈730 calendar
days at 60m, ≈60 days at 30m) means the 30Min arm cannot even reach the directional-read floor,
let alone pair with the 60Min arm for the SUB_PLAN's registered 30m-vs-60m comparison at
comparable depth. yfinance is disqualified as a stand-in for the full 6-cell grid — using it
would silently narrow the study to an unregistered, single-cadence, DIRECTIONAL-at-best probe,
which is not what was pre-registered. No numbers from this fallback check are used as a result;
they are reported only as feasibility evidence, per the SUB_PLAN's "not an extra trial: nothing
is selected on it" framing (stated there about the IEX/SIP concordance check, applied here to
the same honesty standard).

### §2.4 Fetch helper (built, tested, and run — this is the deliverable of step 1)

`backtest/run_fetch_spy_intraday.py` (new): a GET-only Alpaca Market Data REST fetch helper,
following the `fx_data.py`/`options_data.RealAlpacaSource`/`run_orb_probe._fetch_alpaca`
precedent — `resolve_keys()` (env-var lookup, both naming conventions), `fetch_bars()`
(paginated `GET /v2/stocks/{symbol}/bars`, validated via `intraday_data.validate_ohlc`),
`fetch_and_save()` (writes a local CSV under `data/intraday/`, gitignored, and reports row
count + SHA256 + `intraday_data.describe_power()` per cadence — so a future run's provenance is
citable without ever committing bar data), and a `main()` CLI that sweeps every requested
timeframe and returns the DATA-BLOCKED count. `tests/test_run_fetch_spy_intraday.py` (new, 12
cases, all green, no test ever touches the real network — the module's own `_fetch_page` network
seam is monkeypatched throughout): key resolution and its precedence, the missing-keys
`FetchUnavailableError` path, pagination, empty-result handling, a malformed-bar
`DataQualityError` propagation, the SHA256/CSV round trip, and the CLI's blocked-count return
value.

This is the "fetch" half of step 1's hard gate, run for real in this session — its result is
§2.1 above. The helper is ready to deliver the full grid's data the moment
`ALPACA_API_KEY_ID`/`ALPACA_API_SECRET_KEY` (or the TS-side names) are set in the environment.

## §3 Verdict — DATA-BLOCKED

**Neither the Alpaca fetch nor an operator local drop-in materializes SPY intraday bars in this
environment/session.** Per the SUB_PLAN's own stop condition, this is a complete deliverable:
no arm of the 6-cell grid is run, no per-arm number is computed or fabricated, and the frozen
grid design (§1) plus this evidence (§2) are recorded so the next attempt does not re-litigate
feasibility from scratch. `backtest/tested_cells.py` gets two `DATA_BLOCKED` records (§5) — one
per registered cadence arm (`hourly` / 60m and `30m`), 3 cells each (the R grid), consistent
with the `n_cells` accounting the existing ledger uses for a 2-axis grid split by cadence.

### What would change the verdict

Re-running `python3 -m backtest.run_fetch_spy_intraday` with `ALPACA_API_KEY_ID` /
`ALPACA_API_SECRET_KEY` (or `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`) set — the read-only
market-data keys, never a broker order credential — or dropping pre-fetched
`SPY_60min.csv`/`SPY_30min.csv`/`SPY_5min.csv` files under `data/intraday/` would immediately
unblock steps 2–5 (pre-registration commit, the `scripts/emit_hourly_decisions.ts` signal
emitter and its live-record concordance sanity gate, `backtest/hourly_geometry.py` +
`run_hourly_geometry_study.py` + `tests/test_hourly_geometry.py`, and the results/verdict doc) —
none of which are blocked by anything other than this data gate. Egress to
`data.alpaca.markets` is confirmed open in this environment (§2.1), so the only missing
ingredient is credentials or a local file.

## §4 Verification

- `venv/bin/python -m pytest tests/test_run_fetch_spy_intraday.py` — 12 passed.
- `venv/bin/python -m pytest tests/` — full suite green (904 passed, pre-existing 892 + 12 new),
  confirming this package changes nothing else in the Python research path.
- `git diff main --stat` (this PR) touches only `backtest/run_fetch_spy_intraday.py`,
  `tests/test_run_fetch_spy_intraday.py`, `backtest/tested_cells.py`, and this doc — nothing
  under `supabase/functions/`, `supabase/migrations/`, `.env.example`, or any README config
  table.
- No broker order endpoint is referenced anywhere in this package (grep confirms no
  `/v2/orders`, no `positions` DELETE, no `createAlpacaClient` — none of these Python modules
  import `supabase/functions/_shared/alpaca.ts` at all; it is a TS module, out of Python's import
  graph entirely).

## §5 `tested_cells.py` records (this section mirrors the two new ledger entries verbatim)

```
family="hourly_bracket_geometry_sizing", cadence="hourly", vehicle="SPY",
exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DATA_BLOCKED, power="NONE",
source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-data-feasibility.md",
date="2026-08-13"

family="hourly_bracket_geometry_sizing", cadence="30m", vehicle="SPY",
exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=DATA_BLOCKED, power="NONE",
source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-data-feasibility.md",
date="2026-08-13"
```
