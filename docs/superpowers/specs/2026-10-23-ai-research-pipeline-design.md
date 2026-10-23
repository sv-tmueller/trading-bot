# AI research pipeline (Project 1): design

**Date:** 2026-10-23
**Status:** draft, awaiting operator approval
**Origin:** operator brainstorm 2026-10-23, following the research bundle
`docs/research/strategy-landscape-and-risk/` (PR #676) and the sizing question in #675.

---

## 1. Why this exists

The live hourly candlestick rule (`decideHourly`) has no edge: -0.139R per trade on SPY
2016-2026 at 1 bp/side, negative in every calendar year and already negative before costs
(`docs/research/2026-10-22-multi-symbol-hourly-verdict.md`, branch `research/multi-symbol-hourly`).
The research bundle concluded that position sizing, adding symbols, leverage and combining
strategies all multiply an edge that has to exist first. They cannot create one.

The operator wants a bot that trades actively (not buy-and-hold), stays inside a hard drawdown
limit, and earns as much as it honestly can inside that limit. The operator wants AI to do the
research work: find rules, test them, and present the results with facts and figures so the
operator can decide. The trading itself stays a frozen, deterministic rule.

This document covers **Project 1** of a four-part programme: the research pipeline that finds
and proves (or rejects) the first strategy. Nothing in this project trades.

### 1.1 The programme (context only; each later project gets its own design)

| # | Project | Depends on |
|---|---|---|
| 0 | Cleanup: ADR to park the hourly rule, close #675 as "risk-based sizing is the design for the next strategy", fix the pause gap (a pause leaves an open position unmanaged; `hourly-check/logic.ts` returns on `paused` before the session-close flatten) | nothing; small, agreed in chat via `/tm-advisor` |
| 1 | **This document.** AI research pipeline + first strategy candidate round | nothing |
| 2 | Multi-market execution: one frozen rule across several ETFs, multi-day holds, overnight-gap-aware sizing, drawdown brakes | a Project 1 candidate the operator promotes |
| 3 | Months-long paper trial and real-money gate | Project 2 |
| later | Higher trading frequency, then possibly leverage (futures before options) | a rule proven in Project 3 |

## 2. Operator goals, in the operator's terms

- **Hard limit: 30% maximum drawdown** of the whole portfolio. When return and drawdown conflict,
  the drawdown cap wins.
- **Within that limit, as much return as the strategy honestly allows.** The operator's
  aspiration was about 60% a year; the research shows that a return-to-drawdown ratio of 2 would
  rank among the best published track records, so the target is "maximize under the cap", not a
  fixed return number.
- **Active, not buy-and-hold.** The bot takes real positions and trades often enough to be
  judged in reasonable time.
- **One strategy** (consistent with the CLAUDE.md "One decision rule" invariant). A single rule
  may trade several markets.
- **Scale by markets first, frequency later.** The first rule trades a basket of liquid ETFs
  across asset classes; faster trading is a later, separately tested step.
- **Positions may be held for several days** (swing horizon).
- **Trust before real money:** strategies proven over long history, then the whole automation
  running for months on paper (Project 3).
- **AI is the researcher, rules are the trader.** AI proposes, specifies and tests rules; a rule
  that passes is frozen and trades with no AI in the loop.
- **The operator decides.** The AI recommends, with facts and figures. **Every approach is a
  GitHub issue**, so the whole programme is documented.

## 3. Non-goals and anti-goals

**Non-goals for Project 1:**
- No production code. Nothing under `supabase/functions/` changes.
- No broker calls of any kind (`CLAUDE_AGENT_NO_BROKER=1` for every research session).
- No scheduled or autonomous research loop. Rounds start when the operator asks.
- No leverage in the pass/fail test: gross exposure is capped at 100% of equity. Short positions
  are allowed (operator decision, 2026-10-23). A 1.5x-leverage line is shown in the scorecard for
  information only; it never decides a verdict.
- No options or futures studies in this round.
- No multi-strategy combination (one rule goes forward).

**Anti-goals** (failure even if everything "works"):
- **The AI tunes until something passes.** A rule found by trying hundreds of variants and
  reporting the winner is a fluke generator. Every variant tried must count against the bar.
- **Re-testing a killed idea and treating it as new evidence.** The ledger
  (`backtest/tested_cells.py`) must be checked first, and overlap stated honestly.
- **Results presented without the luck tests**, or a headline number without its drawdown.
- **Any AI model in the trading path**, now or as a side door (e.g. an LLM "confirming" signals).

## 4. Constraints

- CLAUDE.md "Architectural invariants" apply in full and are a review gate.
- Research code lives in `backtest/` (Python 3.9, every file starts with
  `from __future__ import annotations`) and is never imported by `supabase/functions/`.
- Pre-registration discipline (`docs/research/README.md`, "Dated research memos"): the test plan
  is frozen and merged in one PR strictly before any result; results go in a second PR.
- Overfitting gate (`backtest/overfitting_gate.py`, usage in
  `docs/research/2026-07-21-overfitting-gate-usage.md`): DSR >= 0.95, PBO < 0.5, bootstrap
  CI_low > 0 on uplift. Inputs (N, S, block length, n_boot) frozen in the pre-registration.
- Every tested cell is appended to `backtest/tested_cells.py` in the results PR.
- New prose avoids em dashes (CLAUDE.md "Writing conventions").

## 5. How the pipeline works

```
Operator: "start a research round"
  -> AI proposes 3-5 candidates            (one GitHub issue each, label `candidate`)
  -> Operator picks which to test           (decision 1, on the issues)
  -> Pre-registration freeze PR             (plan, grid, costs, bar, holdout; merged before results)
  -> Study runs on daily data               (analyst agent, research-only)
  -> Results PR + verdict doc + ledger rows
  -> Scorecard posted on each issue         (fixed facts-and-figures format, with a recommendation)
  -> Operator decides                       (decision 2: promote / reject / retest at full power)
  -> Promoted rule becomes the input to Project 2
```

### 5.1 Candidate issues

A new label `candidate` ("Strategy candidate from the AI research pipeline; operator decides").
Each issue uses a fixed body:

1. **Idea** in one paragraph, plus the exact rule (entry, exit, sizing) in plain words.
2. **Why it might work:** the economic or behavioural reason, with citations (the research bundle
   and its sources are the starting library).
3. **Evidence so far:** published results, with evidence grade (academic / practitioner /
   marketing).
4. **Novelty check:** output of `check_novel` against `backtest/tested_cells.py`, and an honest
   statement of overlap with killed families.
5. **Data feasibility:** instruments, history length, data source.
6. **Proposed test:** grid size N (counts toward the programme budget, see 5.4), windows, costs.
7. **AI recommendation:** test or don't test, and why.

### 5.2 The pass bar (my proposal; the operator confirms it in the freeze PR)

A candidate passes only if **all** hold:

1. **Drawdown headroom.** Sized to a portfolio volatility target (frozen in the
   pre-registration; the default is 10% annualised), the worst drawdown is at most **20%**, both
   in the development period and in the holdout. The 10-point gap to the 30% cap is headroom for
   a future worse than the past. Because gross exposure is capped at 100% (no leverage), the
   target is a ceiling: a calm basket may run below it, and the scorecard reports the realised
   volatility.
2. **Better than SPY at the same risk.** The benchmark is SPY run through **the same daily
   volatility-targeting mechanism** and the same exposure cap, not SPY scaled once after the
   fact. This isolates the signal from the volatility scaling (much of trend following's
   apparent edge is the scaling itself; `strategies.md`). After costs and German tax (the
   existing `backtest/tax.py` `annual_netting` mode), the median walk-forward-window Calmar beats
   that benchmark. The same benchmark is the baseline for the bootstrap uplift test.
3. **Survives the luck tests.** The overfitting gate passes on all three legs, with DSR computed
   from the **programme's stored trial Sharpes** (5.4), not just this candidate's grid.
4. **Holds up on unseen data.** On the holdout period (5.3) the rule is profitable after costs
   and stays inside the drawdown limit.
5. **Actually active** (operator decision, 2026-10-23). At least **20 round-trip trades per year**
   on average across the basket, where a round trip is one ETF position opened and later closed
   (or reversed); volatility-target resizes of an existing position do not count. And **no single
   ETF is held more than 90% of the time**. Together these keep the result from quietly being
   buy-and-hold without excluding weekly or monthly rebalancing rules.

The existing bar (after-tax Calmar vs unscaled SPY, 1.3085 median-window, n_w = 13;
`docs/research/2026-07-21-leveraged-contracts-preregistration.md` §4) is reported alongside for
continuity but is not the gate here, because it compares strategies at different risk levels.

### 5.3 Holdout period

The data splits into a **development period** (data start to 2021-12-31) and a **holdout**
(2022-01-01 to the data end, which includes the 2022 bear market). All development, selection,
walk-forward windows, DSR and PBO use the development period only. The harness enforces this
mechanically: holdout bars are not loadable until the candidate's development-period result is
recorded in the results PR, and the holdout is then run exactly once. A candidate that is
re-tested after seeing the holdout loses its holdout; the re-test must say so.

Honest limit: the AI has read published research that covers some of these years, so the
holdout guards against our own tuning, not against the literature's.

### 5.4 Programme-wide trial budget

Every configuration tested across all rounds is stored with its per-period return series (or at
least its Sharpe ratio on the common scale), not just counted, because
`overfitting_gate.deflated_sharpe_ratio` needs the full vector of trial Sharpes. DSR in criterion
5.2.3 uses that programme-wide vector, so each extra variant raises the bar for every later one.

Which earlier trials count (my call): trials in the **same hypothesis space** (daily-bar
allocation rules on SPY or ETF baskets: TSMOM, Faber, GEM, GTAA-lite, vol-targeting) count and are
re-run into the store during round 1's backfill (section 6). Unrelated spaces (intraday
candlestick, ORB, 4h forex, scalping) stay in the ledger for novelty checks but do not enter this
programme's DSR vector, because their Sharpes are on different cadences and markets.

The first round's budget is at most **50 new configurations** across all candidates; raising it
is an operator decision recorded on the round's issue.

### 5.5 The scorecard (posted on each candidate issue at results)

| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | | |
| CAGR after German tax | | |
| Max drawdown, and its dates | | |
| Calmar (return / max drawdown) | | |
| Sharpe; target and realised annualised volatility | | |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | | |
| Round trips per year, average holding days, max share of time in one ETF | | |
| Cost drag per year, incl. short-borrow cost; result at double cost | | |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | | |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | | |

Followed by: **verdict** (pass / fail per criterion), **recommendation** (promote / reject /
retest at full power), and **what would change the recommendation**.

### 5.6 Universe and data

- A fixed list of about 15 liquid US-listed ETFs across asset classes: US and international
  equity, government bonds of several durations, gold, broad commodities, and a USD or currency
  proxy. The builder chooses and freezes the list in the pre-registration, preferring the longest
  common history (likely back to about 2006-2007).
- Daily adjusted bars from yfinance, as the existing research uses. A parity check against Alpaca
  daily bars over a recent overlapping period is required, because live trading will use Alpaca.
- Cost model: start from the repo's existing 0.05% per side and state it; a sensitivity line at
  double cost goes in the scorecard. Short positions pay a stated borrow cost; idle cash earns a
  stated T-bill proxy (the existing survey already uses BIL); the 1.5x information line pays a
  stated financing rate.

### 5.7 First round: seed candidates

From the research bundle (`strategies.md` ranks 1-3 and `roadmap.md` cluster C), the AI's first
proposals are expected to include:

1. **Multi-ETF time-series trend** (each ETF long when its own trend is up, flat or short when
   down; volatility-targeted). Overlap: TSMOM and Faber were tested on SPY alone, and a 5-asset
   GTAA-lite rotation in `docs/research/2026-06-24-candidate-strategy-survey-first-cut.md`; the
   novelty is the broader cross-asset basket with portfolio volatility targeting.
2. **Cross-sectional ETF momentum** (hold the strongest few ETFs by recent relative strength,
   rebalance on a fixed schedule). Untested in this repo.
3. Optionally one **short-horizon swing** candidate on the same basket (for example a short-term
   mean-reversion entry) if its evidence grade justifies spending trial budget on it.

The round proposes; the operator picks. Only one rule is promoted to Project 2.

## 6. What gets built

- **Label and issue template** for `candidate` (5.1) and a scorecard template (5.5).
- **A research-round skill** (`.claude/skills/research-round/SKILL.md`, following the existing
  `research-bundle` skill's orchestrator pattern): proposes candidates, opens issues, drafts the
  freeze PR, dispatches the analyst agent after the freeze merges, posts scorecards. It never
  touches production code or a broker.
- **Backtest support** in `backtest/`: a multi-asset, volatility-targeted portfolio simulator with
  multi-day holds, long and short positions and a 100% gross-exposure cap (the existing
  `simulate_from_signal` accepts only long weights summing to at most 1, so this is an extension,
  not a reuse), borrow/cash/financing costs, round-trip accounting compatible with
  `apply_annual_netting_tax`, the scorecard metrics, the mechanical holdout lock, and the
  programme trial store (5.4).
- **Ledger backfill** before round 1's novelty checks: add the missing records for the 2026-06-24
  first- and second-cut surveys (GEM, Faber, GTAA-lite, vol-target) and the 2026-10-22
  multi-symbol and intraday-momentum studies, so `check_novel` does not report already-tested
  families as new.
- **The first round** itself: candidate issues, freeze PR, results PR, verdict doc, ledger rows,
  scorecards.

**Sequencing:** the tooling can be built straight away. Before round 1's freeze PR, merge the
research bundle (PR #676) and the two 2026-10-22 research branches (`research/multi-symbol-hourly`,
`research/spy-intraday-momentum`), because the candidate issues cite them.

## 7. Left to the builder

- The exact ETF list and start date (frozen in the pre-registration, with reasons).
- Whether the simulator extends `run_candidate_survey.py`'s machinery or `walkforward.py`'s;
  whichever needs less new code.
- Walk-forward window length and count, CSCV splits, bootstrap block length, within the gate
  usage note's guidance.
- How the programme trial store is laid out on disk (it must be diffable and reviewable in a PR,
  consistent with `tested_cells.py`'s design).
- The borrow, cash and financing rates, stated and justified in the pre-registration.

## 8. Decisions

**Operator decisions (2026-10-23):**
- 30% maximum drawdown is the hard limit; return is maximized under it.
- One strategy; scale by markets first, frequency later; multi-day holds allowed.
- AI researches and recommends; the operator decides; every approach is a GitHub issue.
- Shorts allowed in the test; no leverage in the verdict; 1.5x shown for information only.
- Activity floor: 20 round trips per year, no ETF held more than 90% of the time.

**Calls I made (operator to check):**
- Pass bar thresholds: 10% volatility target (a ceiling at 1x), 20% max drawdown.
- Benchmark: SPY through the same volatility-targeting mechanism; also the bootstrap baseline.
- Development period to 2021-12-31; holdout from 2022-01-01, locked in code.
- Programme trial store holds Sharpes, not just a count; same-hypothesis-space prior trials are
  backfilled and count toward DSR; unrelated spaces do not.
- First-round budget of 50 new configurations.
- Operator-triggered rounds, no schedule.
- Two operator decision points per candidate (before testing, after results).
- German tax mode as the after-tax basis, matching existing research.
- Merge PR #676 and the two 2026-10-22 research branches before round 1's freeze PR.
