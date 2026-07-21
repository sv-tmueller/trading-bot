"""Overfitting gate: DSR + PBO/CSCV + moving-block bootstrap.

Research-only. Lives in backtest/ and is never imported by
supabase/functions/. No LLM, no broker calls.

Scaffold — implementation follows in subsequent commits (TDD).
See docs/research/2026-07-21-overfitting-gate-usage.md for the usage note.
"""
from __future__ import annotations
