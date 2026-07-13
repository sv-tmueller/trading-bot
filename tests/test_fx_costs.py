"""Tests for backtest/fx_costs.py — frozen venue cost presets.

Values are pinned VERBATIM to docs/research/2026-07-13-forex-short-horizon-
feasibility-gate.md §4/§5 (the #369 gate doc, merged into #370's batch
contract). All offline / synthetic — no network.
"""
from __future__ import annotations

import pytest

from backtest import fx_costs


# ---------------------------------------------------------------------------
# Preset values match the gate doc verbatim (§4.1-4.3)
# ---------------------------------------------------------------------------

def test_ic_markets_ecn_preset_matches_gate_doc():
    p = fx_costs.IC_MARKETS_ECN
    assert p.base_bp == pytest.approx(1.04)
    assert p.pessimistic_bp == pytest.approx(2.35)
    assert p.has_overnight is True


def test_xtb_cfd_preset_matches_gate_doc():
    p = fx_costs.XTB_CFD
    assert p.base_bp == pytest.approx(0.79)
    assert p.pessimistic_bp == pytest.approx(1.75)
    assert p.has_overnight is True


def test_cme_6e_preset_matches_gate_doc():
    p = fx_costs.CME_6E
    assert p.base_bp == pytest.approx(0.56)
    assert p.pessimistic_bp == pytest.approx(1.00)
    assert p.has_overnight is False


def test_cme_m6e_preset_matches_gate_doc():
    p = fx_costs.CME_M6E
    assert p.base_bp == pytest.approx(1.23)
    assert p.pessimistic_bp == pytest.approx(2.10)
    assert p.has_overnight is False


def test_presets_registry_has_all_four_keyed():
    assert set(fx_costs.PRESETS.keys()) == {"ic_markets", "xtb", "6e", "m6e"}
    assert fx_costs.PRESETS["ic_markets"] is fx_costs.IC_MARKETS_ECN
    assert fx_costs.PRESETS["xtb"] is fx_costs.XTB_CFD
    assert fx_costs.PRESETS["6e"] is fx_costs.CME_6E
    assert fx_costs.PRESETS["m6e"] is fx_costs.CME_M6E


def test_trade_republic_excluded_from_presets():
    """Trade Republic is EXCLUDED as a preset (gate doc: issuer spread
    structurally dominates, no crossover size)."""
    names = {p.name.lower() for p in fx_costs.PRESETS.values()}
    assert not any("trade republic" in n or "traderepublic" in n for n in names)


# ---------------------------------------------------------------------------
# Overnight financing — per-direction, XTB proxy on the $114k notional
# convention (100,000 EUR lot x 1.14 EURUSD ref price, gate doc §5)
# ---------------------------------------------------------------------------

def test_overnight_financing_long_bp_per_night():
    # $4.525 / $114,000 * 10,000 ~= 0.397 bp/night
    bp = fx_costs.overnight_financing_bp_per_night("long")
    assert bp == pytest.approx(0.397, abs=0.001)


def test_overnight_financing_short_bp_per_night():
    # $1.032 / $114,000 * 10,000 ~= 0.0905 bp/night
    bp = fx_costs.overnight_financing_bp_per_night("short")
    assert bp == pytest.approx(0.0905, abs=0.001)


def test_overnight_financing_rejects_unknown_direction():
    with pytest.raises(ValueError):
        fx_costs.overnight_financing_bp_per_night("sideways")


def test_overnight_bp_for_spot_cfd_preset_returns_value():
    assert fx_costs.overnight_bp_for(fx_costs.XTB_CFD, "long") == pytest.approx(0.397, abs=0.001)
    assert fx_costs.overnight_bp_for(fx_costs.IC_MARKETS_ECN, "short") == pytest.approx(0.0905, abs=0.001)


def test_overnight_bp_for_futures_preset_is_none():
    """Futures presets carry NO overnight term (structural, per the gate doc)."""
    assert fx_costs.overnight_bp_for(fx_costs.CME_6E, "long") is None
    assert fx_costs.overnight_bp_for(fx_costs.CME_M6E, "short") is None
