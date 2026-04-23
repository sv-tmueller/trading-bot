from __future__ import annotations

import pandas as pd
import pytest

from backtest.data import fetch_data


def test_fetch_data_returns_ohlcv_columns(mocker):
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1_000_000.0, 1_200_000.0],
        },
        index=pd.date_range("2024-01-02", periods=2, freq="B"),
    )
    mocker.patch("backtest.data.yf.download", return_value=mock_df)

    result = fetch_data("AMD", years=1)

    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(result) == 2


def test_fetch_data_drops_nan_rows(mocker):
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, None],
            "High": [102.0, None],
            "Low": [99.0, None],
            "Close": [101.0, None],
            "Volume": [1_000_000.0, None],
        },
        index=pd.date_range("2024-01-02", periods=2, freq="B"),
    )
    mocker.patch("backtest.data.yf.download", return_value=mock_df)

    result = fetch_data("AMD", years=1)

    assert len(result) == 1


def test_fetch_data_passes_correct_period(mocker):
    mock_download = mocker.patch(
        "backtest.data.yf.download",
        return_value=pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [1e6]},
            index=pd.date_range("2024-01-02", periods=1, freq="B"),
        ),
    )

    fetch_data("NVDA", years=2)

    mock_download.assert_called_once()
    _, kwargs = mock_download.call_args
    assert kwargs.get("period") == "2y" or mock_download.call_args[0][1] == "2y"
