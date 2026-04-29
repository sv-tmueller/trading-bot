from __future__ import annotations

import pytest
from tools.risk import (
    calculate_position,
    check_portfolio_guardrails,
    check_exposure_for_new_order,
)


def test_position_size_1pct_risk():
    result = calculate_position(
        portfolio_value=100_000,
        risk_pct=0.01,
        entry_price=150.0,
        atr=3.0,
        atr_stop_multiplier=1.5,
        rr_ratio_min=2.0,
    )
    # stop_distance = 1.5 * 3.0 = 4.5
    # shares = floor(1000 / 4.5) = 222
    # stop_loss = 150.0 - 4.5 = 145.5
    # take_profit = 150.0 + 4.5 * 2.0 = 159.0
    assert result["shares"] == 222
    assert result["stop_loss"] == pytest.approx(145.5)
    assert result["take_profit"] == pytest.approx(159.0)
    assert result["risk_dollars"] == pytest.approx(1000.0)
    assert result["stop_distance"] == pytest.approx(4.5)


def test_position_size_scales_with_portfolio():
    # stop_distance = 2.0 * 1.0 = 2.0 (evenly divides risk_dollars so floor is exact)
    # small risk_dollars = 500 -> shares = 250; large risk_dollars = 2000 -> shares = 1000
    small = calculate_position(50_000, 0.01, 100.0, 2.0, 1.0, 2.0)
    large = calculate_position(200_000, 0.01, 100.0, 2.0, 1.0, 2.0)
    assert large["shares"] == small["shares"] * 4


def test_guardrails_pass():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.01,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is True
    assert result["reason"] == ""


def test_guardrails_fail_max_positions():
    result = check_portfolio_guardrails(
        open_positions=5,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.01,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "max_positions" in result["reason"]


def test_guardrails_fail_drawdown():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.04,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "drawdown" in result["reason"]


def test_guardrails_fail_exposure():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.22,
        max_exposure=0.20,
        daily_pnl_pct=0.0,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "exposure" in result["reason"]


def test_guardrails_candidate_pct_pushes_over_cap():
    # 18% deployed, candidate would add 5% → 23% post-trade > 20% cap
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.18,
        max_exposure=0.20,
        daily_pnl_pct=0.0,
        drawdown_limit=0.03,
        candidate_pct=0.05,
    )
    assert result["can_trade"] is False
    assert "exposure" in result["reason"]


def test_guardrails_candidate_pct_fits_under_cap():
    # 10% deployed, candidate adds 5% → 15% post-trade < 20% cap
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=0.0,
        drawdown_limit=0.03,
        candidate_pct=0.05,
    )
    assert result["can_trade"] is True


def test_check_exposure_for_new_order_passes_when_under_cap():
    # 0 open, candidate notional $15k against $100k equity → 15% < 20%
    result = check_exposure_for_new_order(
        current_notional=0.0,
        candidate_notional=15_000.0,
        portfolio_value=100_000.0,
        max_exposure=0.20,
    )
    assert result["can_trade"] is True
    assert result["reason"] == ""


def test_check_exposure_for_new_order_rejects_when_candidate_alone_over_cap():
    # Single candidate worth $25k against $100k → 25% > 20%
    result = check_exposure_for_new_order(
        current_notional=0.0,
        candidate_notional=25_000.0,
        portfolio_value=100_000.0,
        max_exposure=0.20,
    )
    assert result["can_trade"] is False
    assert "exposure cap breached" in result["reason"]


def test_check_exposure_for_new_order_rejects_when_total_over_cap():
    # $15k already deployed + $10k candidate → $25k = 25% > 20%
    result = check_exposure_for_new_order(
        current_notional=15_000.0,
        candidate_notional=10_000.0,
        portfolio_value=100_000.0,
        max_exposure=0.20,
    )
    assert result["can_trade"] is False
    assert "25.0%" in result["reason"]


def test_check_exposure_for_new_order_passes_at_exact_cap():
    # Exactly at 20% should pass — strict ">", not ">="
    result = check_exposure_for_new_order(
        current_notional=10_000.0,
        candidate_notional=10_000.0,
        portfolio_value=100_000.0,
        max_exposure=0.20,
    )
    assert result["can_trade"] is True


def test_check_exposure_for_new_order_invalid_portfolio_value():
    # Zero/negative portfolio value should fail-closed (treat as broken broker call)
    result = check_exposure_for_new_order(
        current_notional=0.0,
        candidate_notional=1_000.0,
        portfolio_value=0.0,
        max_exposure=0.20,
    )
    assert result["can_trade"] is False
    assert "portfolio_value" in result["reason"]
