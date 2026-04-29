from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools import earnings as earnings_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    earnings_mod.clear_cache()
    yield
    earnings_mod.clear_cache()


def _mock_yf_ticker(dates):
    """Build a mock yfinance.Ticker whose ``earnings_dates`` index contains the given datetimes."""
    df = pd.DataFrame(index=pd.to_datetime(dates))
    tk = MagicMock()
    tk.earnings_dates = df
    return tk


def test_get_next_earnings_date_returns_first_future():
    today = date(2026, 4, 29)
    future = datetime(2026, 5, 5)
    past = datetime(2026, 1, 20)
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([past, future])):
        nxt = earnings_mod.get_next_earnings_date("AAA", today=today)
    assert nxt == future.date()


def test_get_last_earnings_date_returns_most_recent_past():
    today = date(2026, 4, 29)
    past1 = datetime(2026, 1, 20)
    past2 = datetime(2026, 4, 1)
    future = datetime(2026, 5, 5)
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([past1, past2, future])):
        last = earnings_mod.get_last_earnings_date("BBB", today=today)
    assert last == past2.date()


def test_is_in_blackout_window_true_when_within():
    today = date(2026, 4, 29)
    upcoming = datetime(2026, 5, 2)  # 3 days away
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([upcoming])):
        assert earnings_mod.is_in_blackout_window("CCC", today, blackout_days=5) is True


def test_is_in_blackout_window_false_when_outside():
    today = date(2026, 4, 29)
    far_future = datetime(2026, 6, 30)
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([far_future])):
        assert earnings_mod.is_in_blackout_window("DDD", today, blackout_days=5) is False


def test_is_in_blackout_window_false_when_disabled():
    today = date(2026, 4, 29)
    upcoming = datetime(2026, 4, 30)
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([upcoming])):
        assert earnings_mod.is_in_blackout_window("EEE", today, blackout_days=0) is False


def test_is_in_blackout_window_true_for_recent_past():
    today = date(2026, 4, 29)
    recent_past = datetime(2026, 4, 26)  # 3 days ago
    with patch.object(earnings_mod.yf, "Ticker", return_value=_mock_yf_ticker([recent_past])):
        assert earnings_mod.is_in_blackout_window("FFF", today, blackout_days=5) is True


def test_yfinance_error_returns_none_no_raise():
    today = date(2026, 4, 29)
    with patch.object(earnings_mod.yf, "Ticker", side_effect=RuntimeError("network")):
        assert earnings_mod.get_next_earnings_date("GGG", today=today) is None
        earnings_mod.clear_cache()
        assert earnings_mod.get_last_earnings_date("GGG", today=today) is None
        earnings_mod.clear_cache()
        assert earnings_mod.is_in_blackout_window("GGG", today, blackout_days=5) is False


def test_empty_earnings_dataframe_returns_none():
    today = date(2026, 4, 29)
    tk = MagicMock()
    tk.earnings_dates = pd.DataFrame()
    with patch.object(earnings_mod.yf, "Ticker", return_value=tk):
        assert earnings_mod.get_next_earnings_date("HHH", today=today) is None
        assert earnings_mod.get_last_earnings_date("HHH", today=today) is None
        assert earnings_mod.is_in_blackout_window("HHH", today, blackout_days=5) is False


def test_none_earnings_dataframe_returns_none():
    today = date(2026, 4, 29)
    tk = MagicMock()
    tk.earnings_dates = None
    with patch.object(earnings_mod.yf, "Ticker", return_value=tk):
        assert earnings_mod.get_next_earnings_date("III", today=today) is None
