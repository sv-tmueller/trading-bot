# Colleague repo audit — closing the colleague-audit path

**This note closes the "colleague-audit path" left open by
`docs/research/2026-07-15-forex-4h-survey-verdict.md` (§5/§8, batch #378, issue #379), which stated
the class-kill stop consequence verbatim: *"this class of 4h EUR/USD trading has no demonstrated
edge; do not proceed to an FX-system ADR; the colleague-audit path stays available only if he shares
his actual rules or a broker trade export."* A colleague (`fedansoufiane-commits`) granted read
access to four private repos — `Forexbot`, `KryptoBot`, `soso-ai-quant-lab`, `soso-platform-infra` —
and four read-only tarball surveys were performed on 2026-07-20. This note is batch #405, Package 1,
issue #395, and is written entirely from the sanitized survey digests embedded in issue #395's body —
the repos were not re-fetched to write it.**

**Status: path closed — no candidate clears the pre-registered bar; no strategy change to the live
bot.**

---

## 1. Provenance, access etiquette, sanitization

- **Access.** Read-only access was granted to `fedansoufiane-commits/{Forexbot,KryptoBot,soso-ai-quant-lab,soso-platform-infra}`. Four read-only tarball surveys were performed on 2026-07-20; their sanitized digests are reproduced verbatim (as facts, not as copied code) in issue #395's body and are the sole source for every colleague-side claim in this note.
- **Standing etiquette rule.** Never fork, star, watch, comment on, or open issues on his repos. If a fact ever needs spot re-verification in the future, fetch via `gh api repos/fedansoufiane-commits/<repo>/tarball`, never `git clone` — a clone shows up in his traffic insights and a fork/star/watch is a visible interaction. This package performed no such re-verification: the issue digest is treated as ground truth per its own non-goals ("no re-survey of his repos beyond spot-verification of cited facts").
- **Sanitization.** This note contains zero verbatim code from his repos and zero operational identifiers — no server IPs, hostnames, account numbers, or other identifiers of his infrastructure. All numbers below are transcribed from the sanitized digest, not derived from any fresh inspection of his source.

## 2. What each repo is

### Forexbot ("Soso FX")

A signal-only forward-paper harness for two **daily** FX strategies on 8 majors via cTrader
(Pepperstone). Zero real capital — his own policy pins it at stage 0, EUR 0. Not scalping: his
research backlog explicitly rejects intraday — every London-Open-Range-Breakout variant he tried
lost, and he records the question as closed ("Intraday-Frage endgültig geschlossen").

Two strategies:
1. **Carry** — FRED interest-rate differentials (3-month-smoothed, publication-lag-safe), TS signal diff > 1.0% plus cross-sectional top/bottom-2 confirmation, crash filter. Honest 70/30 holdout Sharpe **+0.30**, deflated Sharpe **0.664** against his own promotion gate of **≥ 0.95** (he documents an earlier in-sample DSR of 0.974 as inflated and does not treat it as a valid gate pass).
2. **Regime** — ADX(14) ≥ 20 → 30-day momentum, else 20-day z-score mean reversion. Full-history Sharpe **−0.25**, zero capital.

Exit is signal-flip; he tested 11 SL/TP overlay variants over 16.5 years and rejected all of them.

Safety stack: vol targeting at 10% p.a., exposure caps, a drawdown brake, a fail-closed file-based
kill switch (missing or corrupt state halts trading), broker reconciliation, per-order Ed25519 human
approval, config-hash forward-run freeze with observation-coverage tracking, and a DSR/PBO gatekeeper
whose self-test asserts that pure noise must fail the gate. No LLM in the trading path.

Warts: a flat monolith, JSON-file state, swallowed exceptions, root deployment, and risk-accepted CVE
pins in the broker TLS path.

### KryptoBot ("Soso Crypto")

A paper-first crypto signal platform (BTC/ETH/SOL, Kraken spot, EUR, long-only). Live mode is
provably fail-closed behind roughly 8 gates. Not scalping: the current version (V3) trades a 4h
Donchian-40 breakout + volume ratio ≥ 1.05, gated by daily EMA200 and 4h EMA50 > EMA200, with an ATR
stop at 2.5x / target at 5x and a triple-barrier exit at ≤ 7 days — swing cadence, not intraday.

His own V2 architecture report killed multi-signal agent voting: unprofitable after costs on **every**
variant, profit factor **0.28–0.83**, locked to research-only status.

The backtester is serious: `shift(1)` signals, `merge_asof` regime alignment (no look-ahead), the
in-progress bar dropped, three cost scenarios, dual fill models (maker-optimistic vs
taker-pessimistic — honest profit-factor degradation **1.355 → 1.282**, which he himself flags as
in-sample/undeflated rather than a promoted result), a DSR + PBO/CSCV gatekeeper, and a 4x
cost-coverage economic gate enforced identically in backtest and live.

Safety: a latch-based circuit breaker with independent persistent kill causes; remote control can
only kill or pause, never resume. No LLM in the trading path. Past incident: credentials were once
committed and have since been revoked; `gitleaks` now runs in CI.

### soso-ai-quant-lab

A governance/control plane sitting above the two bots: Pydantic contracts, an artifact store,
promotion gates, purged walk-forward validation, a RandomForest meta-filter behind a 10-gate
promotion battery (including deflated-Sharpe confidence ≥ 0.95, PBO ≤ 0.50, and a moving-block-
bootstrap 5th-percentile uplift > 0), and an advisory-only local LLM — temperature 0, schema-forced
JSON, force-downgraded whenever it contradicts a hard-gate REJECT. His own ADR for this repo states
the AI cannot calculate official metrics, bypass gates, promote strategies, or place orders.

Zero committed research — the strategy directories contain only `.gitkeep`. His conservative
allocation review pins directional strategies at 0% capital. Golden hex-float numeric-parity tests
pin `numpy`/`polars`/`quantstats` outputs across library upgrades.

Overall assessment from the digest: governance built years ahead of evidence.

### soso-platform-infra

A declarative single-VPS ops/governance repo. By its own status doc, nothing is deployed and zero
live orders have ever been placed anywhere in the ecosystem. Valuable patterns recorded here: push
heartbeats every 5 minutes per bot, a 2-minute dead-man check on the alert dispatcher itself, a
durable alert outbox retried every minute, one-outage-one-alarm dedup, daily verified state backups,
and air-gapped Ed25519 owner-approval key generation. The digest characterizes the rest (~95%) as
aspirational paperwork.

## 3. Rule-family mapping

Each of his implemented (or explicitly killed) rule families, mapped against (a) our killed 33-cell
4h EUR/USD survey (`docs/research/2026-07-15-forex-4h-survey-verdict.md`) and (b) his own recorded
gate results.

| His rule family | vs. our killed survey | vs. his own gates | Verdict |
|---|---|---|---|
| Intraday breakouts (London ORB, Forexbot) | Not a 4h EUR/USD cell in our 33, but the same intraday-edge question; our intraday-focused work is `docs/research/2026-06-23-scalping-cost-wall-demonstration.md` and `docs/research/2026-06-23-short-horizon-feasibility-gate.md`, both cost-wall kills | Killed by him — every ORB variant lost; "Intraday-Frage endgültig geschlossen" | Fully covered — independently killed on both sides |
| Daily FX carry (Forexbot) | Not in our 33-cell 4h class (different cadence) | Fails his own promotion gate: deflated Sharpe 0.664 < his required ≥ 0.95 | No honest evidence clears any bar |
| Daily FX regime — ADX gate → momentum / z-score mean-reversion (Forexbot) | Same trend/momentum/mean-reversion families our 33-cell survey killed 0/33 | Full-history Sharpe −0.25, zero capital deployed | Fails outright on his own numbers |
| Multi-signal agent voting (KryptoBot V2) | Structurally the same architecture as our pre-pivot v1.14 bot | Killed by him — PF 0.28–0.83 after costs on every variant, locked research-only | Both killed independently for the same structural reason (see `docs/decisions/2026-07-06-keep-200dma-regime-signal.md` for our incumbent-vs-multi-signal reasoning) |
| 4h Donchian breakout (KryptoBot V3) | Closest analog to our killed T2 Donchian-20/55 cells — all non-survivors in the 33-cell table | In-sample/undeflated by his own admission (fill-model PF 1.355 → 1.282), never promoted through his own gates, EUR 0 capital | Unpromoted on both sides |
| SL/TP overlays (Forexbot) | Matches our survey's no-TP/SL baseline design (state-based baselines 2–4, §7 of the verdict) | He tested 11 variants over 16.5 years and rejected all of them | Consistent finding on both sides |

## 4. Formal outcome

Every rule family he has actually implemented is either (a) already covered by a cell our 33-cell
survey killed, or (b) fails his own promotion/gatekeeper thresholds on his own recorded numbers.
Nothing anywhere in his ecosystem trades real money — Forexbot is EUR 0/stage 0, KryptoBot's live
mode is fail-closed behind ~8 gates with V2 locked research-only and V3 unpromoted, soso-ai-quant-lab
has zero committed research and pins directional strategies at 0% capital, and soso-platform-infra
has deployed nothing and placed zero live orders by its own status doc.

No candidate — his or ours — clears our pre-registered bar: SPY buy-and-hold's median after-tax
Calmar of ~1.31 (**1.309** per Table 6.1 of `docs/research/2026-07-15-forex-4h-survey-verdict.md`;
the best cell across every cost row and both tax modes in that survey reached only 0.337). **No
strategy change to the live bot.**

Invariant #1 (one decision rule) is unaffected by this note — see CLAUDE.md's
[Architectural invariants](../../CLAUDE.md#architectural-invariants) section.

## 5. Adopt / defer engineering list

**Adopt:**
- **Dead-man alert** (→ batch #405 Package 2, #396) — we currently have no independent detector for a silently-dead cron; his platform-infra repo's 2-minute dead-man check on the alert dispatcher itself is the pattern to port.
- **Durable notification outbox** (→ Package 3, #397) — today a failed Discord post (`notifications.ts`) is swallowed and lost; his durable alert outbox retried every minute with one-outage-one-alarm dedup closes that gap.
- **DSR/PBO overfitting gate** (→ Package 4, #398) — his gatekeeper-with-noise-self-test pattern (assert pure noise must fail the gate) is the strongest research-methodology idea surfaced in this audit.

**Defer:**
- **Latch-based circuit breaker** — our `panic`/`pause` plus `kill-switch` combination already covers the operational need at our current complexity budget; a second independent latch layer isn't justified yet.
- **Forward-guard config-hash freeze** — only valuable once we run forward-paper campaigns, which we don't run today.
- **Golden hex-float parity tests** — our TS/Python parity surface is a single pure function (`computeTargetState` in `supabase/functions/_shared/regime.ts`, a 1:1 port of `strategy/regime.py`), already covered by the existing port tests; a numeric-parity harness at his scale is disproportionate here.

## 6. Cross-cutting close

He independently converged on the same architectural principles as this repo — deterministic rules
only, no LLM in the trading path, fail-closed halts, cost-first evaluation — after his own
multi-signal V2 failed the way our pre-pivot v1.14 bot did (see CLAUDE.md's
[Architectural invariants](../../CLAUDE.md#architectural-invariants) section for that history). He
leads only on research-methodology tooling and dead-man monitoring, which is exactly what the adopt
list above takes from his ecosystem. No real money trades anywhere in his four repos.
