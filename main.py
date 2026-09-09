import argparse
import logging
import math
import os
import sys
import tomllib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.config import AppConfig, CONFIG_PATH, load_config
from src.weather_client import fetch_weather_forecast
from src.processing import downsample_weather_data, get_downsampling_interval
from src.database import Database
from src.time_utils import (
    calculate_lead_time_hours,
    floor_to_hour,
    parse_datetime,
    serialize_datetime,
)

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch and store an Open-Meteo weather forecast.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--migrate-only',
        action='store_true',
        help="Run database migrations without fetching forecast data.",
    )
    mode.add_argument(
        '--no-save',
        action='store_true',
        help="Fetch and display forecast data without opening the database.",
    )
    return parser.parse_args()


def configure_logging(config: AppConfig):
    log_filepath = config.log_filepath
    os.makedirs(os.path.dirname(os.path.abspath(log_filepath)), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath),
            logging.StreamHandler(sys.stdout)
        ]
    )


def extract_hourly_data(data: object, config: AppConfig):
    """Extract one weather record per available timestamp."""
    if not isinstance(data, dict):
        raise ValueError("Weather API response must be an object")

    hourly = data.get('hourly')
    if not isinstance(hourly, dict):
        raise ValueError("Weather API response is missing hourly data")

    hourly_time = hourly.get('time')
    if not isinstance(hourly_time, list):
        raise ValueError("Weather API hourly data is missing its timestamp list")
    if not hourly_time:
        raise ValueError("Weather API hourly timestamp list is empty")

    values_by_variable = {}
    for variable in config.weather_variables:
        values = hourly.get(variable)
        if not isinstance(values, list):
            logger.warning(
                "Weather API response is missing valid %s data; storing null values.",
                variable,
            )
            values = []
        elif len(values) != len(hourly_time):
            logger.warning(
                "Weather data length mismatch for %s: received %d timestamps "
                "and %d values. Missing values will be stored as null; values "
                "without timestamps cannot be stored.",
                variable,
                len(hourly_time),
                len(values),
            )
        values_by_variable[variable] = values

    records = []
    for index, timestamp in enumerate(hourly_time):
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError(
                f"Weather API timestamp at index {index} must be a non-empty string"
            )
        timestamp = serialize_datetime(
            parse_datetime(timestamp, "UTC").astimezone(timezone.utc)
        )

        record = {'timestamp': timestamp}
        for variable, values in values_by_variable.items():
            value = values[index] if index < len(values) else None
            value_is_valid = value is None or (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
            )
            if value_is_valid and value is not None:
                try:
                    value_is_valid = math.isfinite(float(value))
                except OverflowError:
                    value_is_valid = False
            if not value_is_valid:
                raise ValueError(
                    f"Weather API value for {variable} at {timestamp} "
                    "must be a finite number or null"
                )
            record[variable] = value
        records.append(record)

    return records


def collect_weather_forecast(config: AppConfig, db: Database | None):
    """Fetch and process the latest weather forecast, optionally persisting it."""
    logger.info("# Performing task... " + ('#' * 14))

    data = fetch_weather_forecast(config)
    capture_time = datetime.now(timezone.utc)
    reference_time = floor_to_hour(capture_time)

    logger.info(
        "Capture time: %s | Reference time: %s",
        capture_time,
        reference_time,
    )
    logger.info("Data fetched.")

    hourly_records = extract_hourly_data(data, config)
    processed_records = downsample_weather_data(
        reference_time,
        hourly_records,
    )

    if db is not None:
        db.save_forecast(
            serialize_datetime(reference_time),
            serialize_datetime(capture_time),
            config.latitude,
            config.longitude,
            processed_records,
        )
        logger.info("Forecast data saved to database.")
    else:
        logger.info("Database save skipped.")

    return reference_time, processed_records, len(hourly_records)


def print_weather_report(
    config: AppConfig,
    reference_time: datetime,
    processed_records: list[dict],
    total_datapoints: int,
):
    """Print the collected forecast as a table."""
    display_timezone = ZoneInfo(config.timezone)
    display_reference_time = reference_time.astimezone(display_timezone)
    display_records = [
        {
            **record,
            'timestamp': serialize_datetime(
                parse_datetime(record['timestamp']).astimezone(display_timezone)
            ),
        }
        for record in processed_records
    ]

    print(
        f"\nDownsampled Weather Report for {config.location_name} "
        f"({config.latitude}, {config.longitude})"
    )
    print(f"Reference time: {display_reference_time}")

    headers = ['Timestamp'] + list(config.weather_variables) + ['Interval']
    widths = []

    for i, header in enumerate(headers):
        if i == 0:
            widths.append(20)
        elif i == len(headers) - 1:
            widths.append(8)
        else:
            widths.append(max(15, len(header)))

    for record in display_records:
        t_str = record['timestamp']
        widths[0] = max(widths[0], len(t_str))

        for j, var in enumerate(config.weather_variables):
            value = record[var]
            if value is not None:
                value_str = f"{value:.2f}"
                widths[j + 1] = max(widths[j + 1], len(value_str))

    header_line = " | ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    print(header_line)

    separator = "---".join("-" * width for width in widths)
    print(separator)

    for record in display_records:
        t_str = record['timestamp']
        row = [t_str]

        for index, var in enumerate(config.weather_variables):
            value = record[var]
            if value is not None:
                row.append(f"{value:<{widths[index+1]}.2f}")
            else:
                row.append(f"{'N/A':>{widths[index+1]}}")

        dt = parse_datetime(t_str)
        lead_time = int(calculate_lead_time_hours(dt, display_reference_time))
        interval = get_downsampling_interval(lead_time)
        row.append(f"{interval}h")

        row_line = " | ".join(f"{row[i]:<{widths[i]}}" for i in range(len(row)))
        print(row_line)

    print(separator)
    print(
        f"Total datapoints: {len(processed_records)} "
        f"/ {total_datapoints}"
    )


def main():
    args = parse_args()
    try:
        config = load_config()
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        logger.error(
            "Could not load configuration from %s: %s",
            CONFIG_PATH,
            error,
        )
        sys.exit(1)

    try:
        configure_logging(config)
    except (OSError, ValueError) as error:
        logger.error(
            "Could not initialize logging at %s: %s",
            config.log_filepath,
            error,
        )
        sys.exit(1)

    db = None
    try:
        if not args.no_save:
            db = Database(
                config.database_path,
                config.timezone,
                weather_variables=config.weather_variables,
            )
            db.init_db()

        if args.migrate_only:
            logger.info("Database migrations completed successfully.")
            return

        reference_time, processed_records, total_datapoints = (
            collect_weather_forecast(config, db)
        )
        print_weather_report(
            config,
            reference_time,
            processed_records,
            total_datapoints,
        )
        logger.info("Task completed successfully.")
    except Exception:
        logger.exception("Task failed")
        raise
    finally:
        if db is not None:
            db.close()
            logger.info('# DB closed. Ending... ###')


if __name__ == "__main__":
    main()
