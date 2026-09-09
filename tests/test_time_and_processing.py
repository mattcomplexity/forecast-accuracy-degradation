from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.processing import downsample_weather_data, get_downsampling_interval
from src.time_utils import (
    calculate_lead_time_hours,
    floor_to_hour,
    normalize_database_datetime,
    parse_datetime,
    serialize_datetime,
)


def test_datetime_helpers_require_timezone_and_normalize_to_utc():
    naive = datetime(2026, 1, 15, 12)

    with pytest.raises(ValueError, match="must include a timezone offset"):
        parse_datetime("2026-01-15T12:00:00")
    with pytest.raises(ValueError, match="timezone-naive"):
        serialize_datetime(naive)

    assert normalize_database_datetime(
        "2026-01-15T12:00:00-05:00"
    ) == "2026-01-15 17:00:00Z"


def test_floor_to_hour_preserves_timezone():
    local_timezone = ZoneInfo("America/New_York")
    value = datetime(2026, 1, 15, 12, 34, 56, 789, tzinfo=local_timezone)

    assert floor_to_hour(value) == datetime(
        2026,
        1,
        15,
        12,
        tzinfo=local_timezone,
    )


def test_lead_time_uses_elapsed_time_across_dst_transition():
    local_timezone = ZoneInfo("America/New_York")
    reference = datetime(2026, 3, 8, 1, 30, tzinfo=local_timezone)
    target = datetime(2026, 3, 8, 3, 30, tzinfo=local_timezone)

    assert calculate_lead_time_hours(target, reference) == 1.0


@pytest.mark.parametrize(
    ("lead_time_hours", "expected_interval"),
    [
        (72, 1),
        (73, 2),
        (168, 2),
        (169, 4),
    ],
)
def test_downsampling_interval_boundaries(
    lead_time_hours: float,
    expected_interval: int,
):
    assert get_downsampling_interval(lead_time_hours) == expected_interval


def test_downsampling_retains_interval_aligned_records_and_normalizes_utc():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [
        {"timestamp": "2026-01-03T23:00:00Z", "lead_time": 71},
        {"timestamp": "2026-01-04T00:00:00Z", "lead_time": 72},
        {"timestamp": "2026-01-07T21:00:00Z", "lead_time": 165},
        {"timestamp": "2026-01-08T00:00:00+02:00", "lead_time": 166},
        {"timestamp": "2026-01-07T23:00:00Z", "lead_time": 167},
        {"timestamp": "2026-01-08T00:00:00Z", "lead_time": 168},
        {"timestamp": "2026-01-08T01:00:00Z", "lead_time": 169},
        {"timestamp": "2026-01-08T02:00:00Z", "lead_time": 170},
        {"timestamp": "2026-01-08T03:00:00Z", "lead_time": 171},
        {"timestamp": "2026-01-08T04:00:00Z", "lead_time": 172},
        {"timestamp": "2026-01-08T05:00:00Z", "lead_time": 173},
        {"timestamp": "2026-01-08T06:00:00Z", "lead_time": 174},
        {"timestamp": "2026-01-08T07:00:00Z", "lead_time": 175},
        {"timestamp": "2026-01-08T08:00:00Z", "lead_time": 176},
    ]

    result = downsample_weather_data(reference, records)

    assert [record["lead_time"] for record in result] == [
        71,
        72,
        166,
        168,
        172,
        176,
    ]
    assert [record["timestamp"] for record in result] == [
        "2026-01-03T23:00:00+00:00",
        "2026-01-04T00:00:00+00:00",
        "2026-01-07T22:00:00+00:00",
        "2026-01-08T00:00:00+00:00",
        "2026-01-08T04:00:00+00:00",
        "2026-01-08T08:00:00+00:00",
    ]
