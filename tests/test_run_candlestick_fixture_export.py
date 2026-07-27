"""Tests for backtest/run_candlestick_fixture_export.py -- the golden-parity fixture
exporter for the candlestick.ts port (#467).

The committed fixture is self-verifying from the Python side: every test here
re-derives its expectations from the SAME committed inputs (never a re-run of a
seeded generator), so the fixture can never silently drift from ``candlestick.py``
and is immune to any future change in numpy's RNG stream.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from backtest import candlestick as cs
from backtest import run_candlestick_fixture_export as exporter

FIXTURE_DIR = "supabase/functions/_shared/testdata"
SHAPES_PATH = f"{FIXTURE_DIR}/candlestick-golden-shapes.json"
SPY_PATH = f"{FIXTURE_DIR}/candlestick-golden-spy.json"


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _bars_to_frame(bars: list) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(bars), freq="D")
    return pd.DataFrame(
        {
            "Open": [b["o"] for b in bars],
            "High": [b["h"] for b in bars],
            "Low": [b["l"] for b in bars],
            "Close": [b["c"] for b in bars],
        },
        index=idx,
    )


def test_committed_fixture_matches_the_python_source():
    """Re-run cs.detect / cs.context_mask / sma_signal on the committed bars and assert
    fires, counts, context masks and SMA are identical to what is recorded."""
    for path in (SHAPES_PATH, SPY_PATH):
        fixture = _load(path)
        for case in fixture["cases"]:
            df = _bars_to_frame(case["bars"])
            for name in fixture["pattern_order"]:
                mask = cs.detect(name, df)
                expected_idx = [int(i) for i in np.flatnonzero(mask.to_numpy())]
                assert case["fires"][name] == expected_idx, (
                    f"{path}:{case['name']}:{name} fires mismatch"
                )
                assert case["counts"][name] == len(expected_idx)
            for ctx in case.get("context", []):
                mask = cs.context_mask(
                    df, ctx["direction"], ctx["mode"], window=ctx["window"]
                )
                expected_admitted = [int(i) for i in np.flatnonzero(mask.to_numpy())]
                assert ctx["admitted"] == expected_admitted, (
                    f"{path}:{case['name']}:context{ctx} mismatch"
                )
            if "sma" in case:
                window = case["sma"]["window"]
                sma = df["Close"].astype(float).rolling(window).mean()
                for i, expected in enumerate(case["sma"]["values"]):
                    got = sma.iloc[i]
                    if expected is None:
                        assert pd.isna(got), f"{path}:{case['name']} sma[{i}] expected NaN"
                    else:
                        assert not pd.isna(got)
                        assert got == pytest.approx(expected, rel=0, abs=1e-9)


def test_thresholds_block_matches_module_constants():
    fixture = _load(SPY_PATH)
    thresholds = fixture["thresholds"]
    assert thresholds["DOJI_BODY_MAX"] == cs.DOJI_BODY_MAX
    assert thresholds["HAMMER_WICK_MIN"] == cs.HAMMER_WICK_MIN
    assert thresholds["HAMMER_OPP_WICK_MAX"] == cs.HAMMER_OPP_WICK_MAX
    assert thresholds["PIN_WICK_MIN"] == cs.PIN_WICK_MIN
    assert thresholds["MARUBOZU_BODY_MIN"] == cs.MARUBOZU_BODY_MIN
    assert thresholds["STAR_BODY_MAX"] == cs.STAR_BODY_MAX
    assert thresholds["CONTEXT_SMA_WINDOW"] == cs.CONTEXT_SMA_WINDOW
    assert thresholds["FIRING_RATE_MAX"] == cs.FIRING_RATE_MAX
    assert thresholds["FIRING_RATE_MIN"] == cs.FIRING_RATE_MIN
    # both committed fixtures carry the same thresholds block
    assert _load(SHAPES_PATH)["thresholds"] == thresholds


def test_registry_block_matches_PATTERNS():
    for path in (SHAPES_PATH, SPY_PATH):
        fixture = _load(path)
        assert fixture["pattern_order"] == list(cs.PATTERNS.keys())
        assert len(fixture["pattern_order"]) == 14
        for name, (_, direction) in cs.PATTERNS.items():
            assert fixture["directions"][name] == direction


def test_every_detector_fires_and_does_not_fire_somewhere():
    """The coverage guarantee: across the union of all cases in both fixtures, every
    one of the 14 detectors has >=1 fire and >=1 non-fire."""
    shapes = _load(SHAPES_PATH)
    spy = _load(SPY_PATH)
    pattern_order = shapes["pattern_order"]
    has_fire = {name: False for name in pattern_order}
    has_non_fire = {name: False for name in pattern_order}
    for fixture in (shapes, spy):
        for case in fixture["cases"]:
            n = len(case["bars"])
            for name in pattern_order:
                fired = set(case["fires"][name])
                if fired:
                    has_fire[name] = True
                if len(fired) < n:
                    has_non_fire[name] = True
    missing_fire = [n for n, v in has_fire.items() if not v]
    missing_non_fire = [n for n, v in has_non_fire.items() if not v]
    assert not missing_fire, f"detectors with zero fires across all cases: {missing_fire}"
    assert not missing_non_fire, (
        f"detectors with zero non-fires across all cases: {missing_non_fire}"
    )


def test_bars_round_trip_bit_exactly():
    """The SPY-fixture bars round-trip through JSON without float drift (they are
    Python float() -> json shortest-round-trip repr -> re-parsed)."""
    fixture = _load(SPY_PATH)
    for case in fixture["cases"]:
        df = _bars_to_frame(case["bars"])
        opens = df["Open"].to_numpy(dtype=np.float64)
        highs = df["High"].to_numpy(dtype=np.float64)
        lows = df["Low"].to_numpy(dtype=np.float64)
        closes = df["Close"].to_numpy(dtype=np.float64)
        rebuilt = exporter._bars_json(df)
        assert np.array_equal(opens, np.array([b["o"] for b in rebuilt]))
        assert np.array_equal(highs, np.array([b["h"] for b in rebuilt]))
        assert np.array_equal(lows, np.array([b["l"] for b in rebuilt]))
        assert np.array_equal(closes, np.array([b["c"] for b in rebuilt]))


def test_export_is_byte_identical_to_the_committed_fixture(tmp_path):
    """Regeneration is deterministic: running the exporter again reproduces the exact
    committed bytes (idempotence)."""
    rc = exporter.main(["--out", str(tmp_path)])
    assert rc == 0
    for name in ("candlestick-golden-shapes.json", "candlestick-golden-spy.json"):
        generated = (tmp_path / name).read_bytes()
        committed = open(f"{FIXTURE_DIR}/{name}", "rb").read()
        assert generated == committed, f"{name} is not byte-identical to the committed copy"


def test_serialized_json_contains_no_nan_or_infinity_tokens():
    for path in (SHAPES_PATH, SPY_PATH):
        with open(path) as fh:
            text = fh.read()
        assert "NaN" not in text
        assert "Infinity" not in text
        # must still be strictly valid JSON (json.load would already raise otherwise)
        json.loads(text)


def test_main_returns_zero_and_writes_both_files(tmp_path):
    rc = exporter.main(["--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "candlestick-golden-shapes.json").exists()
    assert (tmp_path / "candlestick-golden-spy.json").exists()


def test_sma_guard_band_holds_on_the_committed_spy_fixture():
    """No committed SPY bar sits within the guard band of its own 200-window SMA --
    an ULP-level rolling-mean difference between pandas and a naive TS sum could never
    flip a golden boolean."""
    fixture = _load(SPY_PATH)
    for case in fixture["cases"]:
        if "sma" not in case:
            continue
        min_margin = case["sma"]["min_margin"]
        assert min_margin is not None
        assert min_margin >= exporter.SMA_GUARD_MIN_MARGIN
