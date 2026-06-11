# Margin / leverage increase — assessment

**Question:** Operator feels "the results are not sufficient" and wants to "increase margin." Is the dissatisfaction supported by the data, and what would adding broker margin on top of UPRO actually do?
**Issue:** — (operator request, no issue filed)
**Date:** 2026-06-11
**Author:** Analyst (research-only; no production code or settings touched)

> **Environment note:** no market-data network access in this session, so no new backtests were
> run. Every number below is sourced from existing repo artifacts:
> `docs/research/2026-06-05-regime-backtest-pl-winrate.md`,
> `docs/research/mvp2-pcs-riv-backtest.md`,
> `docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md`,
> `docs/CURRENT_CONFIG.md`, and `backtest/regime.py`.

---

## 1. Are the results actually insufficient?

### What the backtests say (2026-06-05 run, `backtest/regime.py`)

| Metric | Strategy 5y | B&H UPRO 5y | B&H SPY 5y | Strategy 10y | B&H UPRO 10y | B&H SPY 10y |
|---|---|---|---|---|---|---|
| Total return | **+146.4%** | +186.5% | +92.0% | **+554.0%** | +1282.9% | +321.6% |
| CAGR | **+19.8%** | +23.4% | +13.9% | **+20.7%** | +30.0% | +15.5% |
| Max drawdown | **−38.1%** | −63.9% | −24.5% | **−50.2%** | −76.8% | −33.7% |
| Round-trips | 12 | — | — | 26 | — | — |
| Win rate | 50% | — | — | 38% | — | — |
| Avg win / avg loss | +27.8% / −6.5% | — | — | +40.1% / −5.6% | — | — |

A ~20% CAGR with roughly half of UPRO's buy-and-hold drawdown is not an "insufficient" backtest.
It beats 1× SPY by ~5–6 pp CAGR in both windows, and the design spec's stated success criterion
was merely "cover its own running costs" (~€60/yr). The strategy is *designed* to trail B&H UPRO
on raw return — the −38% vs −64% (5y) drawdown reduction is the product, per the 2026-06-05 note.

### What live results say: almost nothing yet

Per `docs/CURRENT_CONFIG.md`, the bot is deployed **paper-only** on the dev project, soaking since
**2026-06-05**. Today is 2026-06-11 — that is **~4 trading days** of soak. Over 4 days:

- the regime signal (SPY vs 200-DMA) has at most flipped once, more likely zero times — the
  strategy fires **12 trades in 5 years** (~2.4/yr). Four days contain no statistical information
  about the edge.
- the migration plan itself (pivot spec §9, step 12) mandates a **minimum 1-month paper soak**,
  ideally including one regime flip, before live cutover. We are ~13% of the way through that.

**Conclusion on the feeling:** not supported. There is no result yet to be dissatisfied with; the
backtested result is comfortably above the project's own bar. If the dissatisfaction is "4 days of
paper P&L looks flat," that is the expected behaviour of a 2.4-trades-per-year strategy.

---

## 2. What would "increase margin" concretely mean?

### (a) The account already runs ~3× effective leverage

`BOT_TICKER=UPRO` is a **3× daily-reset leveraged S&P 500 ETF**. On regime-LONG the bot deploys
100% of cash, so the account already carries ~**3× daily SPY beta** (with the swap/financing cost
of 2× notional embedded inside UPRO's expense structure, plus its 0.91% ER). "We have no leverage"
is not the current state; leverage is the core of the design.

### (b) Reg-T margin on top: ~6× effective — and likely not even openable

Stacking Alpaca Reg-T margin (2× initial) on UPRO would target ~**6× effective daily SPY
exposure**. Two problems, one regulatory and one arithmetic:

**Regulatory:** FINRA Notice 09-53 scales maintenance margin for leveraged ETFs by the leverage
factor: a 3× long ETF requires **25% × 3 = 75% maintenance**. A position opened at 2× margin
(50% equity) is *already below* 75% maintenance — i.e., a sustained 2× margined UPRO position is
effectively not permitted; brokers either flag leveraged ETFs non-marginable or margin-call
immediately. (Alpaca's exact treatment of UPRO marginability is unverified in this session — flag
for confirmation — but the FINRA floor binds any US broker.)

**Arithmetic (assume it were possible):** at constant 2× margin, account-equity drawdown ≈ 2×
position drawdown, before financing. Scaling the backtested strategy drawdowns:

| Historical strategy max DD (UPRO, 1×) | Naive 2×-margin equity DD |
|---|---|
| 5y: −38.1% | ≈ **−76%** |
| 10y: −50.2% | ≈ **−100% (account wipeout)** |

And the naive linear scaling **understates** reality for two reasons:
1. **Margin calls intervene first.** Equity hits the maintenance threshold well before −76%; forced
   liquidation crystallises losses at the lows, so the realised path is worse than the
   mark-to-market scaling.
2. **Path dependence / volatility decay.** UPRO's daily reset means a volatile-but-flat SPY grinds
   UPRO down; releveraging that decayed path with margin compounds the grind. Linear DD scaling is
   a *lower bound* on the damage.

**Financing drag:** explicit broker margin interest (order of 5–7%/yr on the borrowed half ≈
2.5–3.5 pp/yr equity drag) stacks on top of UPRO's embedded financing on 2× internal notional. At
~6× effective exposure the combined financing on ~5× borrowed notional is on the order of
**20–30 pp/yr of drag in a flat market**. None of this is modelled in `backtest/regime.py`, which
has no leverage parameter at all.

### (c) Kill-switch interaction

The kill-switch fires on a **25% drawdown of UPRO's price from its 30-trading-day rolling high**
(`KILL_SWITCH_DRAWDOWN_PCT=0.25`, `KILL_SWITCH_LOOKBACK_DAYS=30`). Two scenarios under margin:

- **Trigger unchanged (price-based):** firing *frequency* doesn't change, but each fire now
  liquidates a 2×-margined position — ~**50% account-equity loss per kill-switch event** instead of
  ~25%, plus the no-time-delay re-entry rule (pivot spec §3 decision 6) buys back in at ~6×
  exposure as soon as SPY recrosses the 200-DMA. Two fires = account gone.
- **Trigger re-tuned to protect equity at 25%:** it would have to fire at ~12.5% UPRO price
  drawdown ≈ ~4% SPY pullback within 30 days. SPY has 4–5% 30-day pullbacks multiple times in a
  typical year — the kill-switch becomes a whipsaw machine, systematically selling local lows and
  re-buying higher. The 2026-06-05 note already flags that the kill-switch adds "some whipsaw
  cost" even at current settings; halving the trigger distance multiplies that cost.

Note also the backtest **does not model the kill-switch at all** (daily bars only), so we cannot
currently quantify either scenario — another reason a leveraged variant cannot be approved on
existing evidence.

---

## 3. Risks specific to this proposal

1. **Margin calls / forced liquidation** — the only mechanism by which this strategy can produce a
   permanent total loss. Today's worst case is a deep-but-recoverable drawdown; margin converts
   the 10y backtested −50.2% into a wipeout scenario (§2b).
2. **Leveraged-ETF volatility decay, squared** — UPRO already pays daily-reset decay; broker
   leverage on top compounds path dependence in exactly the choppy regimes where the 200-DMA
   filter whipsaws (38% win rate over 10y — most trades are small whipsaw losses).
3. **This project's own incident history argues for conservatism.** On 2026-05-06 (incident #149),
   agent-side broker access drained paper buying power from **$99k to $2,239** in one minute via
   six unintended market orders, and the failure re-materialised ~30 minutes after the fix issue
   was filed. The entire post-pivot architecture (no LLM in path, one decision rule, panic
   function, broker guard) exists because this project decided risk surface must shrink, not grow.
4. **Architectural invariant:** CLAUDE.md — "one decision rule… Do not add a second decision rule
   without a fresh brainstorm and design spec." A leverage/sizing change alters the risk envelope
   the current spec was approved under (the pivot spec's non-goals explicitly include "does **not**
   attempt to beat SPY by margin trading"). Any margin increase therefore requires a fresh
   brainstorm + spec + operator sign-off, not a parameter tweak.
5. **Prior art in this repo:** both prior attempts to reach for more return (v1.14 LLM swing bot:
   +12.77%/5y vs SPY +86%; PCS-RIV options overlay: best Sharpe 0.14 vs SPY 0.83 → KILL) were
   killed on evidence. "More margin" is the third reach; it should clear the same evidentiary bar.

---

## 4. Recommendation

**Do not increase margin now.** The premise ("results not sufficient") is unsupported: the
backtest shows +19.8–20.7% CAGR vs the project's cost-coverage goal, and the live track record is
4 paper days — too short to judge by roughly an order of magnitude (spec mandates ≥1 month).

### Evidence required before any leverage increase could even be considered

1. **A leveraged-variant backtest** in `backtest/regime.py` (new `--leverage` parameter — Engineer
   task, post-spec) modelling: margin interest at realistic Alpaca rates, FINRA 09-53 maintenance
   (75% for a 3× ETF — this alone may kill the idea at the broker-rules level), forced-liquidation
   paths, and the kill-switch at both trigger calibrations, over both the 5y and 10y windows.
2. **Completion of the planned paper soak** (≥1 month, ideally spanning one regime flip), with
   clean `audit_log` outcomes and zero unintended trades.
3. **An explicit written max-drawdown tolerance from the operator.** The current strategy already
   prints −38% (5y) / −50% (10y). If those numbers are acceptable, margin is unnecessary; if they
   are not, margin is disqualified a fortiori.
4. **Confirmation of UPRO's actual marginability/maintenance treatment at Alpaca** (unverified
   here; no API access in this session).

### Lower-risk responses to "results not sufficient"

- **Wait.** The honest answer to a 4-day paper soak. Re-assess at the 1-month gate.
- **SMA-window sweep** — already supported with zero code changes: `REGIME_SMA_DAYS` is validated
  20–500 in `config.ts`, and `main.py backtest --sma N` sweeps it offline. A research note
  comparing e.g. 100/150/200/250 on the 10y window is a cheap, invariant-respecting study.
- **More capital, not more leverage.** Returns scale linearly with capital at the *same* −38%/−50%
  drawdown profile and zero wipeout risk — strictly dominant over margin for an operator who finds
  absolute P&L too small.
- **Bank the free basis points already identified:** the backtest assumes cash earns 0%; T-bill
  yield during cash periods would add "a couple of %" to CAGR per the 2026-06-05 note. If
  implemented (fresh spec required — it touches the trading path), this raises returns with *less*
  risk, not more.

**Bottom line:** the feeling is premature, the mechanism (margin on a 3× ETF) is the highest-risk
lever available and likely blocked by FINRA maintenance rules anyway, and the project's own
history and invariants demand a brainstorm + spec + leveraged backtest before touching sizing.
Recommend: defer, finish the soak, and optionally commission the SMA-sweep study in the meantime.
