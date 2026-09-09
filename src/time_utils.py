from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def parse_datetime(value: str, timezone_name: str | None = None) -> datetime:
    """Parse an ISO timestamp, optionally assigning a timezone when it is naive."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        if timezone_name is None:
            raise ValueError(
                f"Timestamp {value!r} must include a timezone offset"
            )
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def serialize_datetime(value: datetime) -> str:
    """Serialize a timezone-aware timestamp in ISO format."""
    if value.tzinfo is None:
        raise ValueError("Cannot serialize a timezone-naive datetime")
    return value.isoformat()


def serialize_database_datetime(value: datetime) -> str:
    """Serialize an aware timestamp as readable, sortable UTC text."""
    if value.tzinfo is None:
        raise ValueError("Cannot serialize a timezone-naive datetime")
    return value.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%SZ"
    )


def normalize_database_datetime(
    value: str,
    timezone_name: str | None = None,
) -> str:
    """Normalize timestamp text, optionally assigning a fallback timezone."""
    return serialize_database_datetime(parse_datetime(value, timezone_name))


def floor_to_hour(value: datetime) -> datetime:
    """Round a timezone-aware datetime down to the start of the hour."""
    if value.tzinfo is None:
        raise ValueError("Cannot floor a timezone-naive datetime")
    return value.replace(minute=0, second=0, microsecond=0)


def calculate_lead_time_hours(target: datetime, reference: datetime) -> float:
    """Calculate forecast lead time in hours."""
    if target.tzinfo is None or reference.tzinfo is None:
        raise ValueError("Lead-time calculation requires timezone-aware datetimes")
    target_utc = target.astimezone(timezone.utc)
    reference_utc = reference.astimezone(timezone.utc)
    return (target_utc - reference_utc).total_seconds() / 3600
