from math import sqrt

import pandas as pd
import pytest

from src.forecast_analysis import (
    compute_forecast_analysis_data,
    compute_rmse_data,
)


def test_forecast_analysis_calculates_lead_times_and_signed_errors(
    forecast_df: pd.DataFrame,
):
    result = compute_forecast_analysis_data(forecast_df, "temperature_2m")

    assert result is not None
    assert result["actual_value"].tolist() == [12.0, 12.0, 12.0, 12.0]
    assert result["lead_time"].tolist() == [3, 2, -1, -2]
    assert result["error"].tolist() == [-2.0, 2.0, 0.0, 0.0]


def test_proxy_actual_excludes_positive_lead_times_from_average(
    forecast_df: pd.DataFrame,
):
    forecast_df["temperature_2m"] = [0.0, 6.0, 11.0, 13.0]

    result = compute_forecast_analysis_data(
        forecast_df,
        "temperature_2m",
    )

    assert result is not None
    assert result["actual_value"].tolist() == [12.0] * 4


def test_forecast_analysis_handles_empty_and_no_actual_inputs(
    forecast_df: pd.DataFrame,
):
    assert compute_forecast_analysis_data(
        pd.DataFrame(),
        "temperature_2m",
    ) is None

    result = compute_forecast_analysis_data(
        forecast_df.iloc[:2],
        "temperature_2m",
    )

    assert result is not None
    assert result.empty


def test_rmse_groups_errors_by_sorted_lead_time():
    analysis_df = pd.DataFrame(
        {
            "lead_time": [2, 1, 2, 1],
            "error": [3.0, 4.0, 4.0, 0.0],
        }
    )

    result = compute_rmse_data(analysis_df)

    assert result["lead_time"].tolist() == [1, 2]
    assert result["rmse"].tolist() == pytest.approx([sqrt(8.0), sqrt(12.5)])
