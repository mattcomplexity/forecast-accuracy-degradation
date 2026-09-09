import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from src.config import AppConfig, MAX_API_RETRY_DELAY_SECONDS

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable_request_error(error: requests.RequestException) -> bool:
    if isinstance(
        error,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.JSONDecodeError,
        ),
    ):
        return True
    return (
        isinstance(error, requests.HTTPError)
        and error.response is not None
        and error.response.status_code in RETRYABLE_HTTP_STATUS_CODES
    )


def _describe_request_error(error: requests.RequestException) -> str:
    if isinstance(error, requests.exceptions.JSONDecodeError):
        return f"Weather API response was not valid JSON: {error}"
    return f"API request failed: {error}"


def _get_retry_after_seconds(error: requests.RequestException) -> float | None:
    response = error.response
    if response is None or response.status_code not in (429, 503):
        return None

    retry_after = response.headers.get("Retry-After")
    if retry_after is None:
        return None

    if retry_after.isdigit():
        try:
            seconds = int(retry_after)
        except ValueError:
            return None
        return float(min(seconds, MAX_API_RETRY_DELAY_SECONDS))

    try:
        retry_at = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delay = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    return min(delay, MAX_API_RETRY_DELAY_SECONDS)


def fetch_weather_forecast(
    config: AppConfig,
    past_days: int = 1,
    forecast_days: int = 16,
) -> dict:
    """
    Fetch weather data from Open-Meteo using UTC timestamps and relative days.
    """
    params = {
        "latitude": config.latitude,
        "longitude": config.longitude,
        "hourly": ",".join(config.weather_variables),
        "timezone": "UTC",
        "past_days": past_days,
        "forecast_days": forecast_days
    }

    total_attempts = config.api_max_retries + 1
    for attempt in range(total_attempts):
        try:
            response = requests.get(
                config.api_url,
                params=params,
                timeout=config.api_timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            error_description = _describe_request_error(error)
            if not _is_retryable_request_error(error):
                logger.error("%s; not retrying", error_description)
                raise

            if attempt >= config.api_max_retries:
                logger.error(
                    "%s after %d attempts",
                    error_description,
                    total_attempts,
                )
                raise

            exponential_delay = min(
                config.api_retry_base_delay * (2 ** attempt),
                MAX_API_RETRY_DELAY_SECONDS,
            )
            retry_after = _get_retry_after_seconds(error)
            delay = retry_after if retry_after is not None else exponential_delay
            logger.warning(
                "%s (attempt %d/%d). Retrying in %g seconds...",
                error_description,
                attempt + 1,
                total_attempts,
                delay,
            )
            time.sleep(delay)
