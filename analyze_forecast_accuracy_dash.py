import colorsys
import logging
import random
import sqlite3
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from dash import Dash, dcc, html, Input, Output, ctx

from src.config import (
    AppConfig,
    CONFIG_PATH,
    WEATHER_VARIABLE_METADATA,
    format_weather_variable,
    load_config,
)
from src.database import Database
from src.forecast_analysis import (
    compute_forecast_analysis_data,
    compute_overlay_data,
    compute_rmse_data,
    compute_traces_data,
)
from src.time_utils import parse_datetime

logger = logging.getLogger(__name__)


class DashboardStartupError(RuntimeError):
    """Report an expected failure while creating the dashboard server."""


# Utility functions

TIMESTAMP_COLOR_SCALE = [
    [0.0, '#006cff'],
    [0.2, '#00afbd'],
    [0.4, '#00a33c'],
    [0.6, '#d8c600'],
    [0.8, '#ed6500'],
    [1.0, '#ff1f00'],
]


def get_random_color() -> str:
    """Generate a bright random color for overlay traces."""
    h = random.random()
    s = random.uniform(0.7, 1.0)
    v = random.uniform(0.8, 1.0)

    rgb = colorsys.hsv_to_rgb(h, s, v)
    return f'rgb({int(rgb[0] * 255)},{int(rgb[1] * 255)},{int(rgb[2] * 255)})'


def get_timestamp_color_map(timestamps: pd.Series) -> dict[str, str]:
    """Map ordered timestamps from cold to warm colors."""
    ordered = timestamps.drop_duplicates().sort_values()
    positions = np.linspace(0, 1, len(ordered)) if len(ordered) > 1 else [0]
    colors = sample_colorscale(TIMESTAMP_COLOR_SCALE, positions)
    return {str(timestamp): color for timestamp, color in zip(ordered, colors)}


def limit_lines(
    df: pd.DataFrame,
    group_column: str,
    line_limit: int | None,
) -> pd.DataFrame:
    """Select evenly spaced line groups while preserving their complete data."""
    groups = df[group_column].drop_duplicates().sort_values()
    if line_limit is None or len(groups) <= line_limit:
        return df

    selected = groups.iloc[np.linspace(0, len(groups) - 1, line_limit, dtype=int)]
    return df[df[group_column].isin(selected)]


# Data loading

def load_data(config: AppConfig) -> pd.DataFrame:
    """Load forecasts from SQLite with timestamp columns normalized to UTC."""
    db = Database(
        config.database_path,
        config.timezone,
        read_only=True,
        weather_variables=config.weather_variables,
    )
    try:
        rows = db.get_all_forecasts()
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([dict(row) for row in rows])
        df['reference_time'] = pd.to_datetime(
            df['reference_time'].map(parse_datetime),
            utc=True,
        )
        df['target_time'] = pd.to_datetime(
            df['target_time'].map(parse_datetime),
            utc=True,
        )

        return df
    finally:
        db.close()


def get_forecast_analysis_data(
    df: pd.DataFrame,
    selected_var: str,
    cache: dict[str, pd.DataFrame],
) -> pd.DataFrame | None:
    """Return enriched forecast analysis data, computing once per variable."""
    if selected_var not in cache:
        forecast_analysis_df = compute_forecast_analysis_data(df, selected_var)
        if forecast_analysis_df is None:
            return None

        cache[selected_var] = forecast_analysis_df

    return cache.get(selected_var)


# Figure builders

def build_rmse_figure(rmse_df: pd.DataFrame, selected_var: str) -> go.Figure:
    metadata = WEATHER_VARIABLE_METADATA[selected_var]
    fig = px.line(
        rmse_df,
        x='lead_time',
        y='rmse',
        title=(
            'Forecast Accuracy (RMSE) vs Lead Time - '
            f'{metadata["display_name"]}'
        ),
        labels={
            'lead_time': 'Lead Time (hours)',
            'rmse': f'RMSE ({metadata["unit"]})',
        },
        markers=True,
    )
    fig.update_layout(template='plotly_white')
    return fig


def build_traces_figure(
    traces_df: pd.DataFrame,
    selected_var: str,
    timezone_name: str,
) -> go.Figure:
    traces_df = traces_df.assign(
        target_time=traces_df['target_time'].dt.tz_convert(timezone_name)
    )
    metadata = WEATHER_VARIABLE_METADATA[selected_var]
    color_map = get_timestamp_color_map(traces_df['target_time'])
    traces_df = traces_df.assign(line_time=traces_df['target_time'].astype(str))
    fig = px.line(
        traces_df,
        x='lead_time',
        y='error',
        color='line_time',
        color_discrete_map=color_map,
        title=(
            'Forecast Error Traces by Target Time - '
            f'{metadata["display_name"]}'
        ),
        labels={
            'lead_time': 'Lead Time (hours)',
            'error': f'Error ({metadata["unit"]})',
            'line_time': 'Target Time',
        },
        template='plotly_white',
    )

    if len(traces_df['target_time'].unique()) > 20:
        fig.update_layout(showlegend=False)

    fig.add_hline(y=0, line_dash="dash", line_color="black")
    return fig


def build_overlay_figure(
    overlay_df: pd.DataFrame,
    selected_var: str,
    timezone_name: str,
) -> go.Figure:
    overlay_df = overlay_df.assign(
        reference_time=overlay_df['reference_time'].dt.tz_convert(timezone_name),
        target_time=overlay_df['target_time'].dt.tz_convert(timezone_name),
    )
    metadata = WEATHER_VARIABLE_METADATA[selected_var]
    fig = go.Figure()

    for ref_time, group in overlay_df.groupby('reference_time'):
        group = group.sort_values('target_time')
        color = get_random_color()

        fig.add_trace(
            go.Scatter(
                x=group['target_time'],
                y=group[selected_var],
                mode='lines',
                name=str(ref_time),
                line=dict(width=1, color=color),
                opacity=0.7,
            )
        )

        x_coords = pd.to_numeric(group['target_time']).values
        y_coords = group[selected_var].values.astype(float)
        target_x = pd.to_numeric(pd.Series([ref_time])).iloc[0]
        interp_val = np.interp(target_x, x_coords, y_coords)

        fig.add_trace(
            go.Scatter(
                x=[ref_time],
                y=[interp_val],
                mode='markers',
                marker=dict(size=4, color=color),
                showlegend=False,
            )
        )

    fig.update_layout(
        title=(
            f'Forecasted {metadata["display_name"]} '
            'Values Over Target Time by Reference Time'
        ),
        xaxis_title='Target Time',
        yaxis_title=format_weather_variable(selected_var),
        template='plotly_white',
        showlegend=len(overlay_df['reference_time'].unique()) <= 20,
    )
    return fig


# App factory

def build_dashboard_layout(config: AppConfig):
    return html.Div(
        [
            html.H1(
                "Forecast Accuracy Analysis Dashboard",
                style={'textAlign': 'center', 'fontFamily': 'sans-serif'},
            ),
            html.Div(
                [
                    html.Button(
                        "Refresh Data",
                        id='refresh-data-button',
                        n_clicks=0,
                    ),
                    html.Label("Select Weather Variable:"),
                    dcc.Dropdown(
                        id='variable-dropdown',
                        options=[
                            {
                                'label': format_weather_variable(var),
                                'value': var,
                            }
                            for var in config.weather_variables
                        ],
                        value=(
                            config.weather_variables[0]
                            if config.weather_variables
                            else None
                        ),
                        style={'width': '300px'},
                    ),
                    html.Label("Maximum Lines (blank = all):"),
                    dcc.Input(
                        id='line-limit-input',
                        type='number',
                        min=1,
                        step=1,
                        value=20,
                        debounce=True,
                        style={'width': '120px'},
                    ),
                ],
                style={
                    'display': 'flex',
                    'alignItems': 'center',
                    'gap': '8px',
                    'padding': '20px',
                    'backgroundColor': '#f9f9f9',
                    'borderRadius': '10px',
                    'marginBottom': '20px',
                    'width': 'fit-content',
                },
            ),
            dcc.Tabs(
                id='chart-tabs',
                value='rmse',
                children=[
                    dcc.Tab(label='RMSE vs Lead Time', value='rmse'),
                    dcc.Tab(label='Forecast Error Traces', value='traces'),
                    dcc.Tab(label='Forecast Overlay', value='overlay'),
                ],
            ),
            dcc.Loading(
                html.Div(id='charts-container'),
            ),
        ]
    )


def render_active_chart(
    df: pd.DataFrame,
    selected_var: str | None,
    active_tab: str | None,
    line_limit: int | None,
    forecast_analysis_cache: dict[str, pd.DataFrame],
    timezone_name: str,
):
    """Render the selected dashboard tab.

    RMSE and trace rendering may populate ``forecast_analysis_cache``; callers
    must clear it when ``df`` changes. ``line_limit`` applies to trace and
    overlay groups. Chart timestamps are presented in ``timezone_name``.
    Missing data or invalid selections produce status content.
    """
    if df.empty:
        return html.Div("No forecast data available.")
    if selected_var is None:
        return html.Div("Select a weather variable.")

    needs_forecast_analysis_data = active_tab in ('rmse', 'traces')
    forecast_analysis_df = (
        get_forecast_analysis_data(
            df,
            selected_var,
            forecast_analysis_cache,
        )
        if needs_forecast_analysis_data
        else None
    )
    if needs_forecast_analysis_data and (
        forecast_analysis_df is None or forecast_analysis_df.empty
    ):
        return html.Div(
            "No forecast analysis data available for the selected variable."
        )

    if active_tab == 'rmse':
        rmse_df = compute_rmse_data(forecast_analysis_df)
        return dcc.Graph(
            figure=build_rmse_figure(rmse_df, selected_var),
            style={
                'width': '600px',
                'height': '450px',
                'margin': '0 auto',
            },
        )

    if active_tab == 'traces':
        traces_df = compute_traces_data(forecast_analysis_df)
        traces_df = limit_lines(traces_df, 'target_time', line_limit)
        return dcc.Graph(
            figure=build_traces_figure(
                traces_df,
                selected_var,
                timezone_name,
            )
        )

    if active_tab == 'overlay':
        overlay_df = compute_overlay_data(df, selected_var)
        overlay_df = limit_lines(overlay_df, 'reference_time', line_limit)
        if overlay_df.empty:
            return html.Div(
                "No forecast data available for the selected variable."
            )
        return dcc.Graph(
            figure=build_overlay_figure(
                overlay_df,
                selected_var,
                timezone_name,
            )
        )

    return html.Div("Select a chart tab.")


def create_app(config: AppConfig) -> Dash:
    """Create the dashboard and eagerly load its initial forecast history.

    The loaded frame and analysis cache live in the callback closure. Refresh
    replaces both as one state generation. Initial loading errors propagate;
    callback errors are logged and shown as status content.
    """
    app = Dash(__name__)
    dashboard_state: tuple[pd.DataFrame, dict[str, pd.DataFrame]] = (
        load_data(config),
        {},
    )

    app.layout = build_dashboard_layout(config)

    @app.callback(
        Output('charts-container', 'children'),
        [
            Input('variable-dropdown', 'value'),
            Input('chart-tabs', 'value'),
            Input('line-limit-input', 'value'),
            Input('refresh-data-button', 'n_clicks'),
        ],
    )
    def update_active_chart(
        selected_var: str | None,
        active_tab: str | None,
        line_limit: int | None,
        _refresh_clicks: int,
    ):
        nonlocal dashboard_state
        try:
            if ctx.triggered_id == 'refresh-data-button':
                dashboard_state = (load_data(config), {})

            df_all, forecast_analysis_cache = dashboard_state

            return render_active_chart(
                df_all,
                selected_var,
                active_tab,
                line_limit,
                forecast_analysis_cache,
                config.timezone,
            )
        except Exception:
            logger.exception(
                "Could not update dashboard chart for variable %r and tab %r",
                selected_var,
                active_tab,
            )
            return html.Div(
                "Could not update the dashboard. Check the server logs for details."
            )

    return app


def create_server():
    """Create the Flask WSGI application."""
    try:
        config = load_config()
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise DashboardStartupError(
            f"Could not load configuration from {CONFIG_PATH}: {error}"
        ) from error

    try:
        app = create_app(config)
    except sqlite3.Error as error:
        database_path = Path(config.database_path)
        if not database_path.exists():
            message = (
                f"Forecast database not found at {database_path}. "
                "Create it with: uv run python main.py --migrate-only"
            )
        elif "no such table" in str(error).lower():
            message = (
                f"Forecast database at {database_path} is not initialized: "
                f"{error}. Initialize it with: "
                "uv run python main.py --migrate-only"
            )
        else:
            message = f"Could not read forecast database at {database_path}: {error}"
        raise DashboardStartupError(message) from error
    except OSError as error:
        raise DashboardStartupError(
            f"Could not access dashboard files: {error}"
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        raise DashboardStartupError(
            f"Could not load forecast data: {error}"
        ) from error

    return app.server


# Runner

if __name__ == "__main__":
    print('Loading...')
    try:
        server = create_server()
        print("Starting Dash server on http://127.0.0.1:8050...")
        server.run(debug=True, port=8050)
    except Exception:
        logger.exception("Dashboard failed")
        raise
