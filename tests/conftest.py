from collections.abc import Iterator

import pandas as pd
import pytest

from src.config import AppConfig
from src.database import Database


@pytest.fixture
def app_config(tmp_path) -> AppConfig:
    return AppConfig(
        location_name="Test Location",
        timezone="UTC",
        latitude=40.0,
        longitude=-74.0,
        api_url="https://example.test/forecast",
        api_timeout=10,
        api_max_retries=2,
        api_retry_base_delay=1,
        log_filepath=str(tmp_path / "app.log"),
        database_path=":memory:",
        weather_variables=("temperature_2m",),
    )


@pytest.fixture
def forecast_df() -> pd.DataFrame:
    df = pd.DataFrame(
        [
            ["2026-01-15T00:00:00Z", "2026-01-15T03:00:00Z", 10.0],
            ["2026-01-15T01:00:00Z", "2026-01-15T03:00:00Z", 14.0],
            ["2026-01-15T04:00:00Z", "2026-01-15T03:00:00Z", 12.0],
            ["2026-01-15T05:00:00Z", "2026-01-15T03:00:00Z", 12.0],
        ],
        columns=["reference_time", "target_time", "temperature_2m"],
    )
    df["reference_time"] = pd.to_datetime(df["reference_time"], utc=True)
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True)
    return df


@pytest.fixture
def database(app_config: AppConfig) -> Iterator[Database]:
    db = Database(
        app_config.database_path,
        app_config.timezone,
        weather_variables=app_config.weather_variables,
    )
    db.init_db()
    try:
        yield db
    finally:
        db.close()
