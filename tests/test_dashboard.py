from unittest.mock import Mock

from dash import dcc, html
import pandas as pd
import pytest

import analyze_forecast_accuracy_dash as dashboard


def test_forecast_analysis_cache_reuses_data_for_same_variable(
    monkeypatch: pytest.MonkeyPatch,
    forecast_df: pd.DataFrame,
):
    analysis_df = pd.DataFrame(
        {
            "target_time": pd.to_datetime(["2026-01-15T03:00:00Z"], utc=True),
            "lead_time": [3],
            "error": [-2.0],
        }
    )
    compute = Mock(return_value=analysis_df)
    cache = {}
    monkeypatch.setattr(dashboard, "compute_forecast_analysis_data", compute)

    first_result = dashboard.get_forecast_analysis_data(
        forecast_df,
        "temperature_2m",
        cache,
    )
    second_result = dashboard.get_forecast_analysis_data(
        forecast_df,
        "temperature_2m",
        cache,
    )

    assert first_result is analysis_df
    assert second_result is analysis_df
    assert cache["temperature_2m"] is analysis_df
    compute.assert_called_once_with(forecast_df, "temperature_2m")


def test_render_active_chart_returns_status_for_empty_data():
    result = dashboard.render_active_chart(
        pd.DataFrame(),
        selected_var="temperature_2m",
        active_tab="rmse",
        line_limit=20,
        forecast_analysis_cache={},
        timezone_name="UTC",
    )

    assert isinstance(result, html.Div)
    assert result.children == "No forecast data available."


@pytest.mark.parametrize("active_tab", ["rmse", "traces", "overlay"])
def test_render_active_chart_dispatches_supported_tabs(
    active_tab: str,
    forecast_df: pd.DataFrame,
):
    result = dashboard.render_active_chart(
        forecast_df,
        selected_var="temperature_2m",
        active_tab=active_tab,
        line_limit=20,
        forecast_analysis_cache={},
        timezone_name="UTC",
    )

    assert isinstance(result, dcc.Graph)
