# Overfitting gate: usage note

**Issue:** #398 · **Batch:** #405 (Package 4) · **Date:** 2026-07-21
**Module:** `backtest/overfitting_gate.py` (research-only; never imported by `supabase/functions/`)

This is a short usage memo, not a research bundle (the `docs/research/README.md` four-file
contract applies to `docs/research/<topic>/` survey directories, not standalone dated notes like
this one). It documents when to run each of the three checks in `backtest/overfitting_gate.py` and
how to wire them into a candidate-strategy survey, so future pre-registration specs (this is the
gate #406 and later batches will cite) have a single place to point at.

## The pre-registered bar

A candidate strategy clears the overfitting gate only if **all three** sub-checks pass:

| Check | Threshold | Named constant |
|---|---|---|
| Deflated Sharpe Ratio | `DSR >= 0.95` | `overfitting_gate.DSR_THRESHOLD` |
| Probability of Backtest Overfitting (CSCV) | `PBO < 0.5` | `overfitting_gate.PBO_THRESHOLD` |
| Moving-block bootstrap CI on uplift over baseline | `ci_low > 0` | (bootstrap `alpha`, default 0.05) |

`evaluate_gate(...)` runs all three and returns `{"passed": bool, "dsr", "pbo", "ci_low",
"reasons", ...}` where `reasons` lists which sub-checks failed. Future survey pre-registration
documents should declare, **before** running the survey: `N` (number of trial configurations),
`S` (CSCV `n_splits`), the bootstrap block length (or that the `n**(1/3)` default rule is used),
and `n_boot` — exactly as `backtest/families.py` and the 4h forex pre-registration
(`docs/research/2026-07-13-forex-4h-strategy-preregistration.md`) freeze their grids and windows
before looking at results. None of the three thresholds above is a load-bearing judgment call —
they are the standard values from the cited papers and are overridable per call — but the *inputs*
(`N`, `S`, block length, `n_boot`) should be frozen ahead of time so they can't be quietly re-run
until the gate happens to pass.

## When each check applies

- **Deflated Sharpe Ratio (DSR)** — run after selecting the best of `N` configurations tried in a
  survey, to correct the winner's Sharpe ratio for selection bias and non-normality (skew/kurtosis)
  of its returns. The more configurations tried, the more the raw Sharpe of the "winner" is
  expected to overstate true skill purely by chance; DSR deflates the significance bar accordingly.
  Bailey & Lopez de Prado (2014); the underlying Probabilistic Sharpe Ratio (PSR) building block is
  Bailey & Lopez de Prado (2012).
- **Probability of Backtest Overfitting (PBO) via CSCV** — run whenever a configuration was
  optimized (picked as in-sample-best) over the same history it is then evaluated on, to estimate
  the probability that the in-sample-optimal configuration is out-of-sample mediocre. This is
  complementary to DSR: DSR asks "is the winner's Sharpe still significant after accounting for how
  many trials happened," while PBO asks "does in-sample optimality even transfer out-of-sample at
  all, regardless of significance." Bailey, Borwein, Lopez de Prado & Zhu (2017).
- **Moving-block bootstrap CI** — run to put a confidence interval on a candidate's *uplift over a
  baseline* (e.g. candidate Calmar minus baseline Calmar, per walk-forward OOS window), respecting
  serial dependence in the return series (financial returns are not iid, so a naive iid bootstrap
  would understate the true sampling uncertainty). Kunsch (1989).

## Inputs, and how to source them from the existing harness

- **The `(T, N)` performance matrix** (for PBO) and **the per-config Sharpe vector**
  `all_trial_sharpes` (for DSR) come from the candidate-survey machinery
  (`backtest/run_candidate_survey.py`) — one column per configuration, one row per period, all on
  the **non-annualized** per-period return scale (see "Units" below).
- **`returns_best`** (for DSR) is the raw per-period return series of whichever column is selected
  as the winner (by whatever selection rule the survey uses — full-sample Sharpe, IS-Sharpe from a
  CSCV split, etc. — `deflated_sharpe_ratio` is agnostic to how "best" was chosen).
- **The per-window uplift array** (for the bootstrap) comes from `backtest/walkforward.py`'s
  per-window rows: `candidate_metric[window] - baseline_metric[window]` for each out-of-sample
  window. `block_bootstrap_uplift_ci(candidate, baseline, ...)` is a convenience wrapper that
  differences two equal-length series first if you have raw per-window values rather than
  pre-differenced uplifts.

## Units: the annualization trap

DSR/PSR operate on **non-annualized, per-observation** Sharpe ratios — the `sqrt(n-1)` term in the
PSR z-statistic supplies the horizon scaling internally. Passing an annualized (`x sqrt(252)`) SR
into `probabilistic_sharpe_ratio` or `deflated_sharpe_ratio` is a silent correctness bug. Both
public functions take raw per-period returns and compute the per-observation SR internally, so this
mistake is structurally hard to make; `deflated_sharpe_ratio`'s result dict also reports
`sr_hat_annualized` (`sr_hat * sqrt(252)`) purely for human-readable display.

## No scipy

Per the codebase's no-scipy stance (`docs/architecture/2026-07-05-codebase-map.md`, §4
"Dependency summary", Python 3.9 stack entry — "Options pricing uses stdlib `math` only (no
scipy)"), the module implements
the normal CDF via stdlib `math.erfc` and the inverse-normal (probit) via a clean-room
implementation of Acklam's rational approximation (2003, public domain) with one Halley refinement
step, rather than importing `scipy.stats.norm`.

## References

- Bailey, D. H., & Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection
  Bias, Backtest Overfitting, and Non-Normality. *The Journal of Portfolio Management*, 40(5),
  94-107.
- Bailey, D. H., & Lopez de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. *Journal of
  Risk*, 15(2).
- Bailey, D. H., Borwein, J. M., Lopez de Prado, M., & Zhu, Q. J. (2017). The Probability of
  Backtest Overfitting. *Journal of Computational Finance*, 20(4), 39-69 (working paper: SSRN
  2326253).
- Kunsch, H. R. (1989). The Jackknife and the Bootstrap for General Stationary Observations. *The
  Annals of Statistics*, 17(3), 1217-1241.
- Acklam, P. J. (2003). An algorithm for computing the inverse normal cumulative distribution
  function. Public domain.
