from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests

import main
from src import weather_client
from src.config import AppConfig
from src.database import Database


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"hourly": {}},
        {"hourly": {"time": []}},
    ],
)
def test_extract_hourly_data_rejects_malformed_payloads(
    payload: object,
    app_config: AppConfig,
):
    with pytest.raises(ValueError):
        main.extract_hourly_data(payload, app_config)


@pytest.mark.parametrize(
    ("hourly_values", "expected_values"),
    [
        (None, [None, None]),
        ([7.5], [7.5, None]),
        ([7.5, 8.0, 9.0], [7.5, 8.0]),
    ],
)
def test_extract_hourly_data_handles_missing_and_mismatched_arrays(
    hourly_values: list[float] | None,
    expected_values: list[float | None],
    app_config: AppConfig,
):
    hourly = {
        "time": ["2026-01-15T12:00:00", "2026-01-15T13:00:00"],
    }
    if hourly_values is not None:
        hourly["temperature_2m"] = hourly_values

    records = main.extract_hourly_data({"hourly": hourly}, app_config)

    assert records == [
        {
            "timestamp": "2026-01-15T12:00:00+00:00",
            "temperature_2m": expected_values[0],
        },
        {
            "timestamp": "2026-01-15T13:00:00+00:00",
            "temperature_2m": expected_values[1],
        },
    ]


@pytest.mark.parametrize("invalid_value", [True, "7.5", float("nan"), float("inf")])
def test_extract_hourly_data_rejects_invalid_weather_values(
    invalid_value: object,
    app_config: AppConfig,
):
    payload = {
        "hourly": {
            "time": ["2026-01-15T12:00:00Z"],
            "temperature_2m": [invalid_value],
        }
    }

    with pytest.raises(ValueError, match="finite number or null"):
        main.extract_hourly_data(payload, app_config)


def test_fetch_weather_forecast_retries_timeout_without_real_sleep(
    monkeypatch: pytest.MonkeyPatch,
    app_config: AppConfig,
):
    payload = {"hourly": {"time": ["2026-01-15T12:00:00Z"]}}
    successful_response = Mock()
    successful_response.raise_for_status.return_value = None
    successful_response.json.return_value = payload
    get = Mock(side_effect=[requests.Timeout("timed out"), successful_response])
    sleep = Mock()
    monkeypatch.setattr(weather_client.requests, "get", get)
    monkeypatch.setattr(weather_client.time, "sleep", sleep)

    result = weather_client.fetch_weather_forecast(app_config)

    assert result == payload
    assert get.call_count == 2
    get.assert_called_with(
        app_config.api_url,
        params={
            "latitude": app_config.latitude,
            "longitude": app_config.longitude,
            "hourly": "temperature_2m",
            "timezone": "UTC",
            "past_days": 1,
            "forecast_days": 16,
        },
        timeout=app_config.api_timeout,
    )
    sleep.assert_called_once_with(app_config.api_retry_base_delay)


def test_collect_weather_forecast_saves_only_processed_records(
    monkeypatch: pytest.MonkeyPatch,
    app_config: AppConfig,
):
    payload = {
        "hourly": {
            "time": [
                "2026-01-15T13:00:00Z",
                "2026-01-15T14:00:00Z",
            ],
            "temperature_2m": [7.5, 8.0],
        }
    }
    processed_records = [
        {
            "timestamp": "2026-01-15T14:00:00+00:00",
            "temperature_2m": 8.0,
        }
    ]
    capture_time = datetime(2026, 1, 15, 12, 34, tzinfo=timezone.utc)
    reference_time = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    fetch = Mock(return_value=payload)
    downsample = Mock(return_value=processed_records)
    clock = Mock()
    clock.now.return_value = capture_time
    database = Mock(spec=Database)
    monkeypatch.setattr(main, "fetch_weather_forecast", fetch)
    monkeypatch.setattr(main, "downsample_weather_data", downsample)
    monkeypatch.setattr(main, "datetime", clock)

    result = main.collect_weather_forecast(app_config, database)

    assert result == (reference_time, processed_records, 2)
    fetch.assert_called_once_with(app_config)
    clock.now.assert_called_once_with(timezone.utc)
    downsample.assert_called_once_with(
        reference_time,
        [
            {
                "timestamp": "2026-01-15T13:00:00+00:00",
                "temperature_2m": 7.5,
            },
            {
                "timestamp": "2026-01-15T14:00:00+00:00",
                "temperature_2m": 8.0,
            },
        ],
    )
    database.save_forecast.assert_called_once_with(
        "2026-01-15T12:00:00+00:00",
        "2026-01-15T12:34:00+00:00",
        app_config.latitude,
        app_config.longitude,
        processed_records,
    )
