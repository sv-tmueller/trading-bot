# AI research pipeline artifacts

This directory holds the machine-written artifacts of the AI research pipeline (design:
[`docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md`](../../superpowers/specs/2026-10-23-ai-research-pipeline-design.md)).
Each strategy candidate is a GitHub issue carrying the `candidate` label, filed from the
[candidate issue template](../../../.github/ISSUE_TEMPLATE/candidate.md). The operator decides
which candidates are tested and which are promoted.

## Directory layout

```
docs/research/pipeline/
  README.md                          this file
  trials.json                        programme-wide trial ledger (every tested configuration is stored; see spec 5.4)
  <candidate_id>/
    development_result.json          recorded after the development phase (to 2021)
    holdout_result.json              recorded once, by the single holdout run (2022+)
```

- `trials.json` is the programme-wide trial ledger; its trial count feeds the DSR on every scorecard.
- `<candidate_id>/development_result.json` must exist before the holdout can run.
- `<candidate_id>/holdout_result.json` is written once. The holdout runs a single time per
  candidate; a second write is refused.

## Scorecard template

Posted on each candidate issue at results. Fill the table, then the footer below it.

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
