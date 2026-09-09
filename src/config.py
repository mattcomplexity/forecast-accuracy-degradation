import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Names and default units documented by the Open-Meteo Forecast API.
WEATHER_VARIABLE_METADATA = {
    "temperature_2m": {
        "display_name": "Temperature (2 m)",
        "unit": "°C",
    },
    "relative_humidity_2m": {
        "display_name": "Relative Humidity (2 m)",
        "unit": "%",
    },
    "apparent_temperature": {
        "display_name": "Apparent Temperature",
        "unit": "°C",
    },
    "precipitation_probability": {
        "display_name": "Precipitation Probability",
        "unit": "%",
    },
    "cloud_cover": {
        "display_name": "Cloud Cover Total",
        "unit": "%",
    },
    "wind_speed_10m": {
        "display_name": "Wind Speed (10 m)",
        "unit": "km/h",
    },
    "wind_gusts_10m": {
        "display_name": "Wind Gusts (10 m)",
        "unit": "km/h",
    },
    "precipitation": {
        "display_name": "Precipitation (rain + showers + snow)",
        "unit": "mm",
    },
}

DEFAULT_CONFIG = {
    "location": {
        "name": "New York City",
        "timezone": "America/New_York",
        "latitude": 40.7128,
        "longitude": -74.0061,
    },
    "api": {
        "url": "https://api.open-meteo.com/v1/forecast",
        "timeout": 60,
        "max_retries": 2,
        "retry_base_delay": 53,
    },
    "storage": {
        "log_filepath": "logs/app.log",
        "database_path": "data/weather_history.db",
    },
    "weather": {
        "variables": list(WEATHER_VARIABLE_METADATA),
    },
}

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"
MAX_API_TIMEOUT_SECONDS = 900
MAX_API_RETRIES = 20
MAX_API_RETRY_DELAY_SECONDS = 3600


@dataclass(frozen=True)
class AppConfig:
    location_name: str
    timezone: str
    latitude: float
    longitude: float
    api_url: str
    api_timeout: int
    api_max_retries: int
    api_retry_base_delay: int
    log_filepath: str
    database_path: str
    weather_variables: tuple[str, ...]


def _load_config(path: Path) -> dict:
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except FileNotFoundError:
        return {}


def _get_config_value(config: dict, section: str, key: str):
    section_values = config.get(section, {})
    if not isinstance(section_values, dict):
        raise ValueError(f"Config section [{section}] must be a table")
    return section_values.get(key, DEFAULT_CONFIG[section][key])


def _validate_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _validate_integer(
    value: object,
    key: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{key} must be an integer between {minimum} and {maximum}"
        )
    return value


def _validate_coordinate(
    value: object,
    key: str,
    minimum: float,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return float(value)


def load_config(path: str | Path = CONFIG_PATH) -> AppConfig:
    """Load and validate configuration, using defaults for missing files or keys.

    Invalid sections or weather-variable selections raise ``ValueError``;
    malformed TOML and other file errors propagate to the caller.
    """
    config = _load_config(Path(path))
    location_name = _validate_string(
        _get_config_value(config, "location", "name"),
        "location.name",
    )
    timezone_name = _validate_string(
        _get_config_value(config, "location", "timezone"),
        "location.timezone",
    )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            f"location.timezone is not a recognized timezone: {timezone_name}"
        ) from error

    latitude = _validate_coordinate(
        _get_config_value(config, "location", "latitude"),
        "location.latitude",
        -90.0,
        90.0,
    )
    longitude = _validate_coordinate(
        _get_config_value(config, "location", "longitude"),
        "location.longitude",
        -180.0,
        180.0,
    )

    api_url = _validate_string(
        _get_config_value(config, "api", "url"),
        "api.url",
    )
    if api_url != api_url.strip():
        raise ValueError("api.url must not contain surrounding whitespace")
    try:
        parsed_api_url = urlparse(api_url)
        api_hostname = parsed_api_url.hostname
        api_port = parsed_api_url.port
    except ValueError as error:
        raise ValueError("api.url must be an absolute HTTP or HTTPS URL") from error
    if (
        parsed_api_url.scheme not in ("http", "https")
        or api_hostname is None
        or api_port == 0
    ):
        raise ValueError("api.url must be an absolute HTTP or HTTPS URL")

    api_timeout = _validate_integer(
        _get_config_value(config, "api", "timeout"),
        "api.timeout",
        1,
        MAX_API_TIMEOUT_SECONDS,
    )
    api_max_retries = _validate_integer(
        _get_config_value(config, "api", "max_retries"),
        "api.max_retries",
        0,
        MAX_API_RETRIES,
    )
    api_retry_base_delay = _validate_integer(
        _get_config_value(config, "api", "retry_base_delay"),
        "api.retry_base_delay",
        0,
        MAX_API_RETRY_DELAY_SECONDS,
    )
    log_filepath = _validate_string(
        _get_config_value(config, "storage", "log_filepath"),
        "storage.log_filepath",
    )
    database_path = _validate_string(
        _get_config_value(config, "storage", "database_path"),
        "storage.database_path",
    )

    configured_variables = _get_config_value(config, "weather", "variables")
    if (
        not isinstance(configured_variables, list)
        or not configured_variables
        or not all(isinstance(variable, str) for variable in configured_variables)
    ):
        raise ValueError("weather.variables must be a non-empty list of strings")

    unknown_variables = set(configured_variables) - set(WEATHER_VARIABLE_METADATA)
    if unknown_variables:
        unknown_names = ", ".join(sorted(unknown_variables))
        raise ValueError(f"Unknown weather variables: {unknown_names}")

    if len(configured_variables) != len(set(configured_variables)):
        raise ValueError("weather.variables must not contain duplicates")

    return AppConfig(
        location_name=location_name,
        timezone=timezone_name,
        latitude=latitude,
        longitude=longitude,
        api_url=api_url,
        api_timeout=api_timeout,
        api_max_retries=api_max_retries,
        api_retry_base_delay=api_retry_base_delay,
        log_filepath=log_filepath,
        database_path=database_path,
        weather_variables=tuple(configured_variables),
    )


def format_weather_variable(variable: str) -> str:
    metadata = WEATHER_VARIABLE_METADATA[variable]
    return f'{metadata["display_name"]} [{metadata["unit"]}]'
