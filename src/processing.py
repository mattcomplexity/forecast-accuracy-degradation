from datetime import datetime, timezone

from src.time_utils import (
    calculate_lead_time_hours,
    parse_datetime,
    serialize_datetime,
)


def get_downsampling_interval(lead_time_hours: float) -> int:
    """Return the storage interval for a forecast lead time."""
    if lead_time_hours <= 72:
        return 1
    if lead_time_hours <= 168:
        return 2
    return 4


def downsample_weather_data(
    reference_time: datetime,
    records: list[dict],
) -> list[dict]:
    """
    Downsamples weather data based on the distance from the reference time.
    - 0-3 days: 1h interval
    - 3-7 days: 2h interval
    - 7-16 days: 4h interval

    Input timestamps must be aware; retained timestamps are normalized to UTC.
    """
    downsampled = []
    for record in records:
        dt = parse_datetime(record['timestamp']).astimezone(timezone.utc)
        delta = calculate_lead_time_hours(dt, reference_time)
        interval = get_downsampling_interval(delta)
        keep = int(round(delta)) % interval == 0

        if keep:
            downsampled.append({
                **record,
                'timestamp': serialize_datetime(dt),
            })

    return downsampled
