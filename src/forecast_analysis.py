import numpy as np
import pandas as pd


def compute_forecast_analysis_data(
    df: pd.DataFrame,
    variable: str,
) -> pd.DataFrame | None:
    """Join forecasts to averaged actuals and calculate lead-time errors."""
    if df.empty:
        return None

    actuals_mask = df['reference_time'] > df['target_time']
    actuals_df = (
        df.loc[actuals_mask]
        .groupby('target_time')[variable]
        .mean()
        .reset_index()
    )
    actuals_df.rename(columns={variable: 'actual_value'}, inplace=True)

    merged = pd.merge(df, actuals_df, on='target_time', how='inner')
    merged['lead_time'] = (
        merged['target_time'] - merged['reference_time']
    ).dt.total_seconds() / 3600
    merged['lead_time'] = merged['lead_time'].round().astype(int)
    merged['error'] = merged[variable] - merged['actual_value']

    return merged


def compute_rmse_data(forecast_analysis_df: pd.DataFrame) -> pd.DataFrame:
    rmse_df = forecast_analysis_df.assign(
        sq_error=forecast_analysis_df['error'] ** 2
    )
    rmse_df = (
        rmse_df.groupby('lead_time')['sq_error']
        .mean()
        .apply(np.sqrt)
        .reset_index()
    )
    rmse_df.rename(columns={'sq_error': 'rmse'}, inplace=True)
    rmse_df = rmse_df.sort_values('lead_time')
    return rmse_df


def compute_traces_data(forecast_analysis_df: pd.DataFrame) -> pd.DataFrame:
    return forecast_analysis_df[['target_time', 'lead_time', 'error']].sort_values(
        ['target_time', 'lead_time']
    )


def compute_overlay_data(df: pd.DataFrame, variable: str) -> pd.DataFrame:
    return df[['reference_time', 'target_time', variable]].dropna(subset=[variable])
