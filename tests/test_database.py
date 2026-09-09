import sqlite3

import pytest

from src.database import Database
from src.database_migrations import (
    migrate_database,
    migrate_to_version_1,
    migrate_to_version_2,
)


def test_save_forecast_normalizes_timestamps_and_stores_values(
    database: Database,
):
    database.save_forecast(
        reference_time="2026-01-15T12:00:00-05:00",
        capture_time="2026-01-15T12:05:00-05:00",
        lat=40.0,
        lon=-74.0,
        forecast_records=[
            {
                "timestamp": "2026-01-15T20:00:00+02:00",
                "temperature_2m": 7.5,
                "unconfigured_value": 99.0,
            },
            {"timestamp": "2026-01-15T19:00:00Z"},
        ],
    )

    forecast = database.conn.execute(
        "SELECT reference_time, capture_time, latitude, longitude FROM forecasts"
    ).fetchone()
    values = database.conn.execute(
        "SELECT target_time, temperature_2m "
        "FROM forecast_values ORDER BY target_time"
    ).fetchall()

    assert tuple(forecast) == (
        "2026-01-15 17:00:00Z",
        "2026-01-15 17:05:00Z",
        40.0,
        -74.0,
    )
    assert [tuple(row) for row in values] == [
        ("2026-01-15 18:00:00Z", 7.5),
        ("2026-01-15 19:00:00Z", None),
    ]


def test_save_forecast_rolls_back_parent_and_values_on_duplicate_target(
    database: Database,
):
    with pytest.raises(sqlite3.IntegrityError):
        database.save_forecast(
            reference_time="2026-01-15T12:00:00Z",
            capture_time="2026-01-15T12:05:00Z",
            lat=40.0,
            lon=-74.0,
            forecast_records=[
                {
                    "timestamp": "2026-01-15T18:00:00Z",
                    "temperature_2m": 7.5,
                },
                {
                    "timestamp": "2026-01-15T13:00:00-05:00",
                    "temperature_2m": 8.0,
                },
            ],
        )

    assert database.conn.execute(
        "SELECT COUNT(*) FROM forecasts"
    ).fetchone()[0] == 0
    assert database.conn.execute(
        "SELECT COUNT(*) FROM forecast_values"
    ).fetchone()[0] == 0


def test_deleting_forecast_cascades_to_its_values(database: Database):
    database.save_forecast(
        reference_time="2026-01-15T12:00:00Z",
        capture_time="2026-01-15T12:05:00Z",
        lat=40.0,
        lon=-74.0,
        forecast_records=[
            {
                "timestamp": "2026-01-15T18:00:00Z",
                "temperature_2m": 7.5,
            },
        ],
    )

    with database.conn:
        database.conn.execute("DELETE FROM forecasts")

    assert database.conn.execute(
        "SELECT COUNT(*) FROM forecast_values"
    ).fetchone()[0] == 0


def test_version_3_migration_preserves_legacy_data_and_normalizes_timestamps():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    weather_variables = ("temperature_2m",)

    try:
        migrate_to_version_1(conn, weather_variables, "America/New_York")
        migrate_to_version_2(conn, weather_variables, "America/New_York")
        conn.execute("PRAGMA user_version = 2")
        conn.execute(
            "INSERT INTO forecasts "
            "(id, reference_time, capture_time, latitude, longitude, deleted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                7,
                "2026-01-15 12:00:00",
                "2026-01-15T17:05:00+00:00",
                40.0,
                -74.0,
                0,
            ),
        )
        conn.execute(
            "INSERT INTO forecast_values "
            "(forecast_id, target_time, temperature_2m) VALUES (?, ?, ?)",
            (7, "2026-01-15 15:00:00", None),
        )
        conn.commit()

        migrate_database(conn, weather_variables, "America/New_York")

        forecast = conn.execute(
            "SELECT id, reference_time, capture_time, latitude, longitude, deleted "
            "FROM forecasts"
        ).fetchone()
        value = conn.execute(
            "SELECT forecast_id, target_time, temperature_2m FROM forecast_values"
        ).fetchone()

        assert forecast == (
            7,
            "2026-01-15 17:00:00Z",
            "2026-01-15 17:05:00Z",
            40.0,
            -74.0,
            0,
        )
        assert value == (7, "2026-01-15 20:00:00Z", None)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()
