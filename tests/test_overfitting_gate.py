"""Tests for backtest/overfitting_gate.py.

Offline / synthetic data only (no network). All randomness is explicitly
seeded via ``np.random.default_rng(seed)``. Two tests are mandated by
issue #398's acceptance criteria and must run in the default (non-``slow``)
suite:

- ``test_pure_noise_battery_must_fail_the_gate`` -- a battery of pure-noise
  "strategies" must be rejected by the combined gate, looped over several
  fixed seeds for robustness.
- ``test_synthetic_known_edge_must_pass_the_gate`` -- a battery containing
  one genuine, persistent edge must pass the combined gate.

See docs/research/2026-07-21-overfitting-gate-usage.md for the module's
usage note.
"""
from __future__ import annotations

import numpy as np
import pytest

import backtest.overfitting_gate as og


# ---------------------------------------------------------------------------
# Shared synthetic-data builders (house style: see test_run_candidate_survey.py)
# ---------------------------------------------------------------------------


def _noise_battery(seed: int, n_strats: int, n_periods: int, sigma: float = 0.01) -> np.ndarray:
    """(n_periods, n_strats) matrix of iid zero-mean per-period returns."""
    out = np.empty((n_periods, n_strats), dtype=float)
    for i in range(n_strats):
        rng = np.random.default_rng(seed * 10_000 + i)
        out[:, i] = rng.normal(0.0, sigma, n_periods)
    return out


def _edge_battery(
    seed: int,
    n_strats: int,
    n_periods: int,
    sigma: float = 0.01,
    edge_annualized_sharpe: float = 6.0,
    edge_col: int = 0,
) -> np.ndarray:
    """Like ``_noise_battery`` but column ``edge_col`` carries a genuine drift."""
    out = _noise_battery(seed, n_strats, n_periods, sigma=sigma)
    edge_mu = edge_annualized_sharpe * sigma / np.sqrt(252.0)
    rng = np.random.default_rng(seed * 10_000 + edge_col + 999_999)
    out[:, edge_col] = rng.normal(edge_mu, sigma, n_periods)
    return out


def _per_window_uplift(candidate_col: np.ndarray, baseline_col: np.ndarray, n_windows: int) -> np.ndarray:
    """Chunk two equal-length per-period return series into windows and diff their means."""
    n = len(candidate_col)
    window_len = n // n_windows
    trimmed = window_len * n_windows
    cand = candidate_col[:trimmed].reshape(n_windows, window_len).mean(axis=1)
    base = baseline_col[:trimmed].reshape(n_windows, window_len).mean(axis=1)
    return cand - base


# ---------------------------------------------------------------------------
# Task 1 -- _phi / _probit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("x", [-3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0])
def test_probit_round_trips_through_phi(x):
    assert abs(og._probit(og._phi(x)) - x) < 1e-9


def test_probit_known_quantile_975():
    assert abs(og._probit(0.975) - 1.959964) < 1e-5


def test_probit_known_quantile_median():
    assert abs(og._probit(0.5) - 0.0) < 1e-12


def test_probit_known_quantile_8413447():
    assert abs(og._probit(0.8413447) - 1.0) < 1e-5


def test_phi_at_zero_is_one_half():
    assert og._phi(0.0) == 0.5


def test_phi_known_value():
    assert abs(og._phi(1.959964) - 0.975) < 1e-5


def test_probit_raises_on_zero():
    with pytest.raises(ValueError):
        og._probit(0.0)


def test_probit_raises_on_one():
    with pytest.raises(ValueError):
        og._probit(1.0)


# ---------------------------------------------------------------------------
# Task 2 -- Deflated Sharpe Ratio
# ---------------------------------------------------------------------------


def test_psr_strong_series_small_n_modest_spread_has_high_dsr():
    rng = np.random.default_rng(1)
    returns_best = rng.normal(0.0025, 0.006, 400)  # strong drift, low vol
    trial_sharpes = np.array([0.05, 0.06, 0.055, 0.045, 0.05])  # N=5, tight spread
    result = og.deflated_sharpe_ratio(returns_best, trial_sharpes)
    assert result["dsr"] >= 0.95
    assert result["n_trials"] == 5


def test_dsr_deflation_reduces_with_large_n_wide_spread():
    rng = np.random.default_rng(7)
    returns_best = rng.normal(0.0025, 0.006, 400)

    trial_sharpes_narrow = np.array([0.05, 0.06, 0.055, 0.045, 0.05])  # N=5
    trial_sharpes_wide = np.linspace(-0.3, 0.3, 500)  # N=500, wide spread

    dsr_narrow = og.deflated_sharpe_ratio(returns_best, trial_sharpes_narrow)["dsr"]
    dsr_wide = og.deflated_sharpe_ratio(returns_best, trial_sharpes_wide)["dsr"]

    assert dsr_wide < dsr_narrow


def test_dsr_zero_mean_noise_is_well_below_threshold():
    perf = _noise_battery(seed=123, n_strats=1000, n_periods=750)
    trial_sharpes = og._column_sharpes(perf)
    best = int(np.argmax(trial_sharpes))
    result = og.deflated_sharpe_ratio(perf[:, best], trial_sharpes)
    assert result["dsr"] < 0.95


def test_dsr_raises_for_single_trial():
    with pytest.raises(ValueError):
        og.deflated_sharpe_ratio(np.array([0.01, 0.02, -0.01, 0.03]), np.array([0.5]))


def test_psr_monotone_increasing_in_sr():
    rng = np.random.default_rng(3)
    base = rng.normal(0.0, 0.01, 300)
    shifts = [-0.002, -0.001, 0.0, 0.001, 0.002]
    values = [og.probabilistic_sharpe_ratio(base + s) for s in shifts]
    assert values == sorted(values)


def test_psr_monotone_decreasing_in_sr_benchmark():
    rng = np.random.default_rng(4)
    returns = rng.normal(0.001, 0.01, 300)
    benchmarks = [-0.05, -0.02, 0.0, 0.02, 0.05]
    values = [og.probabilistic_sharpe_ratio(returns, sr_benchmark=b) for b in benchmarks]
    assert values == sorted(values, reverse=True)


def test_psr_raises_for_pathological_denominator(monkeypatch):
    """The PSR denominator (1 - skew*sr + (kurt-1)/4*sr^2) is mathematically
    guaranteed non-negative for the moments of any real distribution, by the
    Pearson moment inequality kurtosis >= skewness**2 + 1: substituting
    x = skew*sr gives denom >= 1 - x + x**2/4 = (1 - x/2)**2 >= 0. So a
    literal negative denominator cannot arise from real return data; this
    test exercises the defensive guard directly by monkeypatching the moment
    estimators with a combination that violates the inequality (kurt=1 with
    skew=3, i.e. kurt < skew**2 + 1).
    """
    returns = np.array([2.0, 0.0, 2.0, 0.0, 2.0, 0.0, 2.0, 0.0])  # sr ~ 0.94
    monkeypatch.setattr(og, "_skewness", lambda r: 3.0)
    monkeypatch.setattr(og, "_kurtosis", lambda r: 1.0)
    with pytest.raises(ValueError):
        og.probabilistic_sharpe_ratio(returns)


def test_psr_denominator_helper_matches_formula():
    assert og._psr_denominator(skew=3.0, kurt=1.0, sr=1.0) == -2.0
    assert og._psr_denominator(skew=0.0, kurt=3.0, sr=0.0) == 1.0


def test_psr_raises_for_single_observation():
    with pytest.raises(ValueError):
        og.probabilistic_sharpe_ratio(np.array([0.01]))


def test_psr_returns_zero_for_flat_returns():
    assert og.probabilistic_sharpe_ratio(np.zeros(10)) == 0.0


def test_psr_returns_zero_for_near_constant_returns():
    """A literally-constant, nonzero return series must not slip past the
    zero-variance guard due to floating-point rounding in std(ddof=1) --
    same bug class as test_column_sharpes_defines_zero_variance_column_as_zero,
    but on the single-series PSR path instead of the vectorized CSCV path.
    """
    assert og.probabilistic_sharpe_ratio(np.full(20, 0.01)) == 0.0


def test_dsr_sr_hat_is_zero_for_near_constant_best_returns():
    """``deflated_sharpe_ratio``'s own zero-variance guard on ``returns_best``
    (used for the reported ``sr_hat``) must use the same tolerance as the PSR
    and CSCV paths, not a strict ``== 0.0`` that floating-point rounding can
    slip past for a literally-constant, nonzero return series.
    """
    trial_sharpes = np.array([0.05, 0.06, 0.055, 0.045, 0.05])
    result = og.deflated_sharpe_ratio(np.full(20, 0.01), trial_sharpes)
    assert result["sr_hat"] == 0.0
    assert result["dsr"] == 0.0


def test_dsr_decreases_as_sr_benchmark_increases():
    """``sr_benchmark`` is additive to the internally computed deflated
    threshold (``sr_star``): raising it makes the bar harder to clear, so
    DSR must be monotonically non-increasing in ``sr_benchmark``.
    """
    rng = np.random.default_rng(4)
    returns_best = rng.normal(0.0025, 0.006, 400)
    trial_sharpes = np.array([0.05, 0.06, 0.055, 0.045, 0.05])
    benchmarks = [0.0, 0.01, 0.02, 0.05]
    values = [
        og.deflated_sharpe_ratio(returns_best, trial_sharpes, sr_benchmark=b)["dsr"]
        for b in benchmarks
    ]
    assert values == sorted(values, reverse=True)
    assert values[0] > values[-1]  # strictly, not just flat-clipped


# ---------------------------------------------------------------------------
# Task 3 -- PBO via CSCV
# ---------------------------------------------------------------------------


def test_pbo_is_deterministic_across_repeated_calls():
    perf = _noise_battery(seed=2, n_strats=10, n_periods=400)
    r1 = og.probability_of_backtest_overfitting(perf, n_splits=8)
    r2 = og.probability_of_backtest_overfitting(perf, n_splits=8)
    assert r1["pbo"] == r2["pbo"]
    assert np.array_equal(r1["logits"], r2["logits"])


def test_pbo_noise_matrix_is_not_degenerate():
    perf = _noise_battery(seed=5, n_strats=10, n_periods=400)
    result = og.probability_of_backtest_overfitting(perf, n_splits=8)
    # Loose sanity bound only -- the robust noise verdict is the combined
    # gate's job (Task 5); CSCV on a small noise sample can land anywhere in
    # a wide band around 0.5.
    assert 0.1 <= result["pbo"] <= 0.9
    assert result["n_combinations"] == 70  # C(8, 4)


def test_pbo_known_edge_column_gives_low_pbo():
    perf = _edge_battery(seed=9, n_strats=10, n_periods=600, edge_annualized_sharpe=8.0)
    result = og.probability_of_backtest_overfitting(perf, n_splits=8)
    assert result["pbo"] < 0.2


def test_pbo_raises_for_odd_n_splits():
    perf = _noise_battery(seed=1, n_strats=5, n_periods=200)
    with pytest.raises(ValueError):
        og.probability_of_backtest_overfitting(perf, n_splits=7)


def test_pbo_raises_for_single_strategy():
    perf = _noise_battery(seed=1, n_strats=1, n_periods=200)
    with pytest.raises(ValueError):
        og.probability_of_backtest_overfitting(perf, n_splits=8)


def test_pbo_raises_when_t_less_than_s():
    perf = _noise_battery(seed=1, n_strats=5, n_periods=4)
    with pytest.raises(ValueError):
        og.probability_of_backtest_overfitting(perf, n_splits=8)


def test_column_sharpes_defines_zero_variance_column_as_zero():
    data = np.column_stack([np.full(20, 0.01), np.linspace(-0.01, 0.01, 20)])
    sharpes = og._column_sharpes(data)
    assert sharpes[0] == 0.0
    assert not np.isnan(sharpes).any()


# ---------------------------------------------------------------------------
# Task 4 -- moving-block bootstrap CI
# ---------------------------------------------------------------------------


def test_block_bootstrap_clearly_positive_uplift_has_positive_ci_low():
    rng = np.random.default_rng(11)
    uplifts = rng.normal(0.01, 0.002, 60)
    result = og.block_bootstrap_ci(uplifts, n_boot=500, seed=0)
    assert result["ci_low"] > 0.0


def test_block_bootstrap_zero_mean_uplift_straddles_zero():
    rng = np.random.default_rng(12)
    uplifts = rng.normal(0.0, 0.01, 60)
    result = og.block_bootstrap_ci(uplifts, n_boot=500, seed=0)
    assert result["ci_low"] <= 0.0 <= result["ci_high"]


def test_block_bootstrap_is_deterministic_for_fixed_seed():
    rng = np.random.default_rng(13)
    uplifts = rng.normal(0.005, 0.01, 40)
    r1 = og.block_bootstrap_ci(uplifts, n_boot=300, seed=42)
    r2 = og.block_bootstrap_ci(uplifts, n_boot=300, seed=42)
    assert r1["ci_low"] == r2["ci_low"]
    assert r1["ci_high"] == r2["ci_high"]
    assert r1["point"] == r2["point"]


def test_block_bootstrap_default_block_length_is_cube_root_rule():
    uplifts = np.arange(64, dtype=float)  # n=64 -> round(64**(1/3)) == 4
    result = og.block_bootstrap_ci(uplifts, n_boot=10, seed=0)
    assert result["block_length"] == 4


def test_block_bootstrap_explicit_block_length_overrides_default():
    uplifts = np.arange(64, dtype=float)
    result = og.block_bootstrap_ci(uplifts, block_length=10, n_boot=10, seed=0)
    assert result["block_length"] == 10


def test_block_bootstrap_block_length_larger_than_n_is_clamped():
    uplifts = np.arange(10, dtype=float)
    result = og.block_bootstrap_ci(uplifts, block_length=100, n_boot=10, seed=0)
    assert result["block_length"] == 10


def test_block_bootstrap_raises_for_single_observation():
    with pytest.raises(ValueError):
        og.block_bootstrap_ci(np.array([0.01]))


def test_block_bootstrap_uplift_ci_differences_two_series():
    candidate = np.array([0.02, 0.03, 0.025, 0.028, 0.021, 0.019, 0.03, 0.027])
    baseline = np.array([0.01, 0.01, 0.011, 0.009, 0.010, 0.012, 0.010, 0.011])
    result = og.block_bootstrap_uplift_ci(candidate, baseline, n_boot=200, seed=0)
    direct = og.block_bootstrap_ci(candidate - baseline, n_boot=200, seed=0)
    assert result["point"] == direct["point"]
    assert result["ci_low"] == direct["ci_low"]


def test_block_bootstrap_uplift_ci_raises_for_unequal_length():
    with pytest.raises(ValueError):
        og.block_bootstrap_uplift_ci(np.array([0.01, 0.02]), np.array([0.01]))


# ---------------------------------------------------------------------------
# Task 5 -- combined gate + mandated fixtures
# ---------------------------------------------------------------------------


def _gate_inputs_from_battery(perf: np.ndarray, baseline_col: int, n_windows: int = 30):
    trial_sharpes = og._column_sharpes(perf)
    best = int(np.argmax(trial_sharpes))
    uplifts = _per_window_uplift(perf[:, best], perf[:, baseline_col], n_windows)
    return {
        "returns_best": perf[:, best],
        "all_trial_sharpes": trial_sharpes,
        "perf_matrix": perf,
        "uplifts": uplifts,
    }


def test_pure_noise_battery_must_fail_the_gate():
    """Mandated (issue #398 AC #2). Loops over several fixed seeds -- the
    combined gate must reject a battery of pure-noise strategies for every
    one of them, and the DSR sub-gate specifically must stay below 0.95 for
    each (the deterministic, seed-robust anti-flake anchor of this test; see
    the module docstring / usage note for why DSR is the reliable noise
    killer -- centering on the expected-max-of-N benchmark keeps the false
    positive rate low, especially at the large N used here).
    """
    for seed in (0, 1, 2, 3, 4):
        perf = _noise_battery(seed=seed, n_strats=600, n_periods=750)
        inputs = _gate_inputs_from_battery(perf, baseline_col=1, n_windows=30)
        result = og.evaluate_gate(
            **inputs,
            pbo_n_splits=8,
            bootstrap_n_boot=500,
            bootstrap_seed=seed,
        )
        assert result["passed"] is False, f"seed={seed}: {result['reasons']}"
        assert result["dsr"] < 0.95, f"seed={seed}: dsr={result['dsr']}"


def test_synthetic_known_edge_must_pass_the_gate():
    """Mandated (issue #398 AC #2). A battery with one genuine, persistent
    edge column must pass the combined gate: DSR clears 0.95 after
    deflating for N trials, PBO is low (the edge column is consistently
    both IS-best and OOS-best), and the block-bootstrap CI on the edge's
    uplift over a noise baseline is significantly positive.
    """
    perf = _edge_battery(
        seed=42, n_strats=50, n_periods=750, edge_annualized_sharpe=6.0, edge_col=0
    )
    inputs = _gate_inputs_from_battery(perf, baseline_col=1, n_windows=30)
    result = og.evaluate_gate(
        **inputs,
        pbo_n_splits=8,
        bootstrap_n_boot=500,
        bootstrap_seed=0,
    )
    assert result["passed"] is True, result["reasons"]
    assert result["dsr"] >= 0.95
    assert result["pbo"] < 0.5
    assert result["ci_low"] > 0.0


def test_evaluate_gate_reasons_lists_failed_subgates():
    perf = _noise_battery(seed=99, n_strats=300, n_periods=750)
    inputs = _gate_inputs_from_battery(perf, baseline_col=1, n_windows=30)
    result = og.evaluate_gate(**inputs, pbo_n_splits=8, bootstrap_n_boot=500, bootstrap_seed=99)
    assert result["passed"] is False
    assert len(result["reasons"]) >= 1
    assert any("dsr" in reason for reason in result["reasons"]) or any(
        "pbo" in reason or "bootstrap" in reason for reason in result["reasons"]
    )
