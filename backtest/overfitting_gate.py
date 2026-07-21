"""Overfitting gate: DSR + PBO/CSCV + moving-block bootstrap.

Research-only. Lives in backtest/ and is never imported by
supabase/functions/. No LLM, no broker calls.

This module combines three independent statistical checks used to decide
whether a strategy found via a research survey (e.g. ``run_candidate_survey``,
``walkforward``) is a genuine edge or an artifact of trying many
configurations against the same history:

1. **Deflated Sharpe Ratio (DSR)** -- corrects the best-of-N trial's Sharpe
   ratio for selection bias and non-normality (skew/kurtosis) of returns.
   Bailey, D. H., & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio:
   Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
   The Journal of Portfolio Management, 40(5), 94-107. The underlying
   Probabilistic Sharpe Ratio (PSR) building block is from Bailey, D. H., &
   Lopez de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier." Journal
   of Risk, 15(2).
2. **Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric
   Cross-Validation (CSCV)** -- estimates how likely the in-sample-optimal
   configuration is to be out-of-sample-mediocre. Bailey, D. H., Borwein,
   J. M., Lopez de Prado, M., & Zhu, Q. J. (2017). "The Probability of
   Backtest Overfitting." Journal of Computational Finance, 20(4), 39-69
   (working paper: SSRN 2326253).
3. **Moving-block bootstrap confidence interval** on a candidate's uplift
   over a baseline across walk-forward out-of-sample windows, respecting
   serial dependence in the return series. Kunsch, H. R. (1989). "The
   Jackknife and the Bootstrap for General Stationary Observations." The
   Annals of Statistics, 17(3), 1217-1241.

``evaluate_gate`` combines all three into a single pass/fail verdict against
the pre-registered bar: ``DSR >= 0.95``, ``PBO < 0.5``, uplift ``ci_low > 0``.
See ``docs/research/2026-07-21-overfitting-gate-usage.md`` for the full usage
note (when each gate applies, how to source inputs from the existing survey
harness, and the pre-registration convention).

No scipy anywhere in this module (the codebase deliberately has no scipy
dependency): the standard normal CDF is ``0.5 * math.erfc(-x / sqrt(2))``
(Abramowitz & Stegun 7.1.1 relation) and the inverse CDF (probit) is a
clean-room implementation of Acklam's rational approximation (Acklam, P. J.
(2003). "An algorithm for computing the inverse normal cumulative
distribution function." Public domain.), refined with a single Halley step
using ``math.erfc`` to reach full double precision. Skewness/kurtosis are
computed from raw ``numpy`` moments, not ``scipy.stats``.

Units / annualization
----------------------
DSR/PSR operate on **non-annualized, per-observation** Sharpe ratios. Passing
an annualized (x sqrt(252)) SR into these functions is a silent correctness
bug -- the sqrt(n-1) term in the PSR z-statistic supplies the horizon
scaling, and mixing units double-counts (or omits) it. The public functions
below take raw per-period returns and compute the per-observation SR
internally so a caller cannot make this mistake; ``deflated_sharpe_ratio``
separately reports an annualized SR in its result dict, clearly labelled,
for human-readable display only.
"""
from __future__ import annotations

import itertools
import math
from typing import Optional, Sequence, Union

import numpy as np

ArrayLike = Union[Sequence[float], np.ndarray]

# Pre-registered gate thresholds (Bailey & Lopez de Prado 2014; Bailey et al.
# 2017). Overridable per call; not load-bearing choices -- see the usage note.
DSR_THRESHOLD = 0.95
PBO_THRESHOLD = 0.5

_EULER_MASCHERONI = 0.5772156649015329


# ---------------------------------------------------------------------------
# Task 1 -- normal-distribution helpers (no scipy)
# ---------------------------------------------------------------------------


def _phi(x: float) -> float:
    """Standard normal CDF, exact to double precision.

    Phi(x) = 0.5 * erfc(-x / sqrt(2))  (Abramowitz & Stegun 7.1.1 relation),
    using the stdlib ``math.erfc``.
    """
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _probit(p: float) -> float:
    """Inverse standard normal CDF (quantile function), no scipy.

    Clean-room implementation of Peter J. Acklam's rational approximation
    (2003, public domain), followed by one Halley refinement step (using
    ``math.erfc``) to reach full double precision.

    Raises ``ValueError`` for ``p`` outside the open interval ``(0, 1)`` --
    callers must never hit this; e.g. the DSR deflator guards ``N >= 2``
    specifically so it never calls ``_probit(0)`` or ``_probit(1)``.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"_probit requires 0 < p < 1, got {p!r}")

    # Coefficients for the rational approximation (Acklam 2003).
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        numerator = (
            ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
        ) * q
        denominator = (
            (((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]
        ) * r + 1.0
        x = numerator / denominator
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # One Halley refinement step to reach full double precision.
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)

    return x


# ---------------------------------------------------------------------------
# Task 2 -- Deflated Sharpe Ratio
# ---------------------------------------------------------------------------


def _skewness(r: np.ndarray) -> float:
    """Population (biased) skewness g1, from raw numpy moments."""
    mean = r.mean()
    m2 = np.mean((r - mean) ** 2)
    m3 = np.mean((r - mean) ** 3)
    if m2 == 0.0:
        return 0.0
    return float(m3 / m2**1.5)


def _kurtosis(r: np.ndarray) -> float:
    """Pearson (non-excess) kurtosis: normal distribution => 3.0."""
    mean = r.mean()
    m2 = np.mean((r - mean) ** 2)
    m4 = np.mean((r - mean) ** 4)
    if m2 == 0.0:
        return 3.0
    return float(m4 / m2**2)


def _psr_denominator(skew: float, kurt: float, sr: float) -> float:
    """Variance term of the PSR z-statistic denominator.

    By the Pearson moment inequality (kurtosis >= skewness**2 + 1), this is
    mathematically guaranteed non-negative for the moments of any real
    distribution -- see ``test_psr_raises_for_pathological_denominator`` for
    the derivation. The guard in ``probabilistic_sharpe_ratio`` exists for
    numerical robustness at the boundary and as defense-in-depth.
    """
    return 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2


def probabilistic_sharpe_ratio(returns: ArrayLike, sr_benchmark: float = 0.0) -> float:
    """Probability that the true Sharpe ratio exceeds ``sr_benchmark``.

    Bailey & Lopez de Prado (2012). Operates on non-annualized, per-
    observation returns; see the module docstring's "Units / annualization"
    section.

    ``std(returns) == 0`` (flat/constant returns) is a documented
    convention: PSR is undefined, and this returns ``0.0`` (no evidence of
    positive skill) rather than raising or emitting a nan.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 2:
        raise ValueError("probabilistic_sharpe_ratio requires at least 2 observations")

    std = r.std(ddof=1)
    if std == 0.0:
        return 0.0

    sr = r.mean() / std
    skew = _skewness(r)
    kurt = _kurtosis(r)
    denom = _psr_denominator(skew, kurt, sr)
    if denom <= 0.0:
        raise ValueError(
            "probabilistic_sharpe_ratio: PSR variance term "
            f"1 - skew*sr + (kurt-1)/4*sr^2 is non-positive ({denom!r}); "
            "cannot compute a valid z-statistic from these moments"
        )

    z = ((sr - sr_benchmark) * math.sqrt(n - 1)) / math.sqrt(denom)
    return _phi(z)


def deflated_sharpe_ratio(
    returns_best: ArrayLike,
    all_trial_sharpes: ArrayLike,
    sr_benchmark: float = 0.0,
) -> dict:
    """Deflated Sharpe Ratio: PSR of the best trial against the expected-max
    Sharpe benchmark implied by having tried ``N`` configurations.

    Bailey & Lopez de Prado (2014). ``all_trial_sharpes`` must be the
    **non-annualized** Sharpe ratios of every configuration tried (including
    the best one); ``returns_best`` is the raw per-period return series of
    the best trial.

    Raises ``ValueError`` if fewer than 2 trials are supplied -- deflating
    for a single trial is undefined (``_probit(1 - 1/1) = _probit(0)``).
    """
    trial_sharpes = np.asarray(all_trial_sharpes, dtype=float)
    n_trials = len(trial_sharpes)
    if n_trials < 2:
        raise ValueError("deflated_sharpe_ratio requires at least 2 trials (N >= 2)")

    variance = trial_sharpes.var(ddof=1)
    sr_star = math.sqrt(variance) * (
        (1.0 - _EULER_MASCHERONI) * _probit(1.0 - 1.0 / n_trials)
        + _EULER_MASCHERONI * _probit(1.0 - 1.0 / (n_trials * math.e))
    )

    dsr = probabilistic_sharpe_ratio(returns_best, sr_benchmark=sr_star + sr_benchmark)

    r_best = np.asarray(returns_best, dtype=float)
    std_best = r_best.std(ddof=1)
    sr_hat = 0.0 if std_best == 0.0 else float(r_best.mean() / std_best)

    return {
        "dsr": dsr,
        "sr_star": sr_star,
        "sr_hat": sr_hat,
        "sr_hat_annualized": sr_hat * math.sqrt(252),
        "n_trials": n_trials,
    }


# ---------------------------------------------------------------------------
# Task 3 -- PBO via CSCV
# ---------------------------------------------------------------------------


def _column_sharpes(data: np.ndarray) -> np.ndarray:
    """Per-column non-annualized Sharpe ratio; 0.0 for zero-variance columns."""
    means = data.mean(axis=0)
    stds = data.std(axis=0, ddof=1)
    safe_stds = np.where(stds > 0.0, stds, 1.0)
    return np.where(stds > 0.0, means / safe_stds, 0.0)


def probability_of_backtest_overfitting(
    perf_matrix: ArrayLike,
    n_splits: int = 16,
    metric: str = "sharpe",
) -> dict:
    """Probability of Backtest Overfitting via Combinatorially Symmetric
    Cross-Validation (CSCV).

    Bailey, Borwein, Lopez de Prado & Zhu (2017). ``perf_matrix`` is a
    ``(T, N)`` array of per-period performance (per-period returns are the
    canonical choice) for ``N`` strategy configurations over ``T`` periods.

    Fully deterministic -- no RNG anywhere; CSCV is exhaustive enumeration of
    all ``C(n_splits, n_splits/2)`` in-sample/out-of-sample splits, so this
    function is the anti-flake building block of the combined gate.

    ``T`` not evenly divisible by ``n_splits`` trims the tail rows (the
    remainder after ``T // n_splits`` full-size blocks) before splitting.
    """
    perf = np.asarray(perf_matrix, dtype=float)
    if perf.ndim != 2:
        raise ValueError("perf_matrix must be 2-D with shape (T, N)")
    t_total, n_strats = perf.shape
    if n_strats < 2:
        raise ValueError(
            "probability_of_backtest_overfitting requires at least 2 strategies (N >= 2)"
        )
    if n_splits % 2 != 0:
        raise ValueError("n_splits (S) must be even")
    if t_total < n_splits:
        raise ValueError("perf_matrix has fewer rows (T) than n_splits (S)")
    if metric != "sharpe":
        raise ValueError(f"unsupported metric {metric!r}; only 'sharpe' is implemented")

    block_size = t_total // n_splits
    trimmed_t = block_size * n_splits
    trimmed = perf[:trimmed_t]
    blocks = [trimmed[i * block_size : (i + 1) * block_size] for i in range(n_splits)]

    half = n_splits // 2
    logits = []

    for is_combo in itertools.combinations(range(n_splits), half):
        is_set = set(is_combo)
        oos_combo = [i for i in range(n_splits) if i not in is_set]

        is_data = np.concatenate([blocks[i] for i in is_combo], axis=0)
        oos_data = np.concatenate([blocks[i] for i in oos_combo], axis=0)

        is_sharpes = _column_sharpes(is_data)
        oos_sharpes = _column_sharpes(oos_data)

        n_star = int(np.argmax(is_sharpes))  # first-max tie-break (np.argmax default)

        rank = int(np.sum(oos_sharpes <= oos_sharpes[n_star]))  # 1 = worst, N = best
        omega = rank / (n_strats + 1)
        logit = math.log(omega / (1.0 - omega))
        logits.append(logit)

    logits_arr = np.asarray(logits, dtype=float)
    pbo = float(np.mean(logits_arr <= 0.0))

    return {
        "pbo": pbo,
        "logits": logits_arr,
        "n_combinations": len(logits_arr),
    }


# ---------------------------------------------------------------------------
# Task 4 -- moving-block bootstrap CI
# ---------------------------------------------------------------------------


def block_bootstrap_ci(
    uplifts: ArrayLike,
    block_length: Optional[int] = None,
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """Moving-block bootstrap confidence interval on the mean of ``uplifts``.

    Kunsch (1989). Overlapping blocks of length ``L`` (default
    ``round(n**(1/3))``, the standard rule) are drawn with replacement and
    concatenated to build each bootstrap resample, respecting serial
    dependence in the series.

    Explicitly seeded (``np.random.default_rng(seed)``) with a fixed
    ``n_boot`` => bit-reproducible. ``block_length > n`` is clamped to ``n``.
    """
    u = np.asarray(uplifts, dtype=float)
    n = len(u)
    if n < 2:
        raise ValueError("block_bootstrap_ci requires at least 2 observations")

    if block_length is None:
        length = max(1, round(n ** (1.0 / 3.0)))
    else:
        length = int(block_length)
        if length < 1:
            raise ValueError("block_length must be >= 1")
    if length > n:
        length = n

    n_blocks_available = n - length + 1
    n_blocks_needed = math.ceil(n / length)

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        starts = rng.integers(0, n_blocks_available, size=n_blocks_needed)
        pieces = [u[s : s + length] for s in starts]
        resample = np.concatenate(pieces)[:n]
        boot_means[i] = resample.mean()

    ci_low, ci_high = np.percentile(boot_means, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    return {
        "point": float(u.mean()),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "block_length": length,
        "n_boot": n_boot,
    }


def block_bootstrap_uplift_ci(
    candidate: ArrayLike,
    baseline: ArrayLike,
    block_length: Optional[int] = None,
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """Convenience wrapper: differences two equal-length series, then bootstraps."""
    c = np.asarray(candidate, dtype=float)
    b = np.asarray(baseline, dtype=float)
    if len(c) != len(b):
        raise ValueError("candidate and baseline must be equal length")
    return block_bootstrap_ci(
        c - b, block_length=block_length, n_boot=n_boot, alpha=alpha, seed=seed
    )


# ---------------------------------------------------------------------------
# Task 5 -- combined gate
# ---------------------------------------------------------------------------


def evaluate_gate(
    *,
    returns_best: ArrayLike,
    all_trial_sharpes: ArrayLike,
    perf_matrix: ArrayLike,
    uplifts: ArrayLike,
    dsr_sr_benchmark: float = 0.0,
    pbo_n_splits: int = 16,
    bootstrap_block_length: Optional[int] = None,
    bootstrap_n_boot: int = 1000,
    bootstrap_alpha: float = 0.05,
    bootstrap_seed: int = 0,
    dsr_threshold: float = DSR_THRESHOLD,
    pbo_threshold: float = PBO_THRESHOLD,
) -> dict:
    """Combined DSR + PBO/CSCV + block-bootstrap overfitting gate.

    ``passed = (dsr >= dsr_threshold) and (pbo < pbo_threshold) and (ci_low > 0)``.
    ``reasons`` lists a human-readable string for each sub-gate that failed.

    Inputs (see docs/research/2026-07-21-overfitting-gate-usage.md for how to
    source these from the existing walkforward/survey harness):
    - ``returns_best`` / ``all_trial_sharpes`` -> ``deflated_sharpe_ratio``.
    - ``perf_matrix`` (T, N) -> ``probability_of_backtest_overfitting``.
    - ``uplifts`` (per-window candidate-minus-baseline) -> ``block_bootstrap_ci``.
    """
    dsr_result = deflated_sharpe_ratio(
        returns_best, all_trial_sharpes, sr_benchmark=dsr_sr_benchmark
    )
    pbo_result = probability_of_backtest_overfitting(perf_matrix, n_splits=pbo_n_splits)
    bootstrap_result = block_bootstrap_ci(
        uplifts,
        block_length=bootstrap_block_length,
        n_boot=bootstrap_n_boot,
        alpha=bootstrap_alpha,
        seed=bootstrap_seed,
    )

    dsr_pass = dsr_result["dsr"] >= dsr_threshold
    pbo_pass = pbo_result["pbo"] < pbo_threshold
    bootstrap_pass = bootstrap_result["ci_low"] > 0.0

    reasons = []
    if not dsr_pass:
        reasons.append(f"dsr {dsr_result['dsr']:.4f} < threshold {dsr_threshold}")
    if not pbo_pass:
        reasons.append(f"pbo {pbo_result['pbo']:.4f} >= threshold {pbo_threshold}")
    if not bootstrap_pass:
        reasons.append(f"bootstrap ci_low {bootstrap_result['ci_low']:.6f} <= 0")

    return {
        "passed": dsr_pass and pbo_pass and bootstrap_pass,
        "dsr": dsr_result["dsr"],
        "pbo": pbo_result["pbo"],
        "ci_low": bootstrap_result["ci_low"],
        "reasons": reasons,
        "dsr_result": dsr_result,
        "pbo_result": pbo_result,
        "bootstrap_result": bootstrap_result,
    }
