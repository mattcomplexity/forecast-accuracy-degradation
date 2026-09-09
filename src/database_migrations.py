import sqlite3
from collections.abc import Sequence

from src.time_utils import normalize_database_datetime


def migrate_to_version_1(
    conn: sqlite3.Connection,
    weather_variables: Sequence[str],
    _timezone_name: str,
):
    """Create or baseline the original application schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_time TIMESTAMP,
            capture_time TIMESTAMP,
            latitude REAL,
            longitude REAL,
            deleted BOOLEAN DEFAULT 0
        )
    """)

    forecast_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(forecasts)")
    }
    if 'deleted' not in forecast_columns:
        conn.execute(
            "ALTER TABLE forecasts ADD COLUMN deleted BOOLEAN DEFAULT 0"
        )

    weather_columns = ", ".join(
        f"{variable} REAL" for variable in weather_variables
    )
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS forecast_values (
            forecast_id INTEGER,
            target_time TIMESTAMP,
            {weather_columns},
            FOREIGN KEY (forecast_id) REFERENCES forecasts(id)
        )
    """)


def migrate_to_version_2(
    conn: sqlite3.Connection,
    _weather_variables: Sequence[str],
    _timezone_name: str,
):
    """Enforce unique target times without rewriting existing data."""
    duplicate = conn.execute("""
        SELECT forecast_id, target_time
        FROM forecast_values
        GROUP BY forecast_id, target_time
        HAVING COUNT(*) > 1
        LIMIT 1
    """).fetchone()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce unique forecast target times while duplicates exist"
        )

    foreign_key_error = conn.execute("PRAGMA foreign_key_check").fetchone()
    if foreign_key_error is not None:
        raise RuntimeError(
            "Cannot enable database constraints while foreign-key errors exist"
        )

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        uq_forecast_values_forecast_target
        ON forecast_values (forecast_id, target_time)
    """)


def migrate_to_version_3(
    conn: sqlite3.Connection,
    weather_variables: Sequence[str],
    timezone_name: str,
):
    """Add value IDs and normalize all stored timestamps to UTC text."""
    conn.execute(
        "ALTER TABLE forecast_values RENAME TO forecast_values_version_2"
    )
    conn.execute("ALTER TABLE forecasts RENAME TO forecasts_version_2")

    conn.execute("""
        CREATE TABLE forecasts (
            id INTEGER PRIMARY KEY,
            reference_time TEXT NOT NULL,
            capture_time TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1))
        )
    """)

    old_forecasts = conn.execute("""
        SELECT id, reference_time, capture_time, latitude, longitude, deleted
        FROM forecasts_version_2
        ORDER BY id
    """).fetchall()
    forecast_rows = [
        (
            row[0],
            normalize_database_datetime(row[1], timezone_name),
            normalize_database_datetime(row[2], timezone_name),
            row[3],
            row[4],
            row[5] if row[5] is not None else 0,
        )
        for row in old_forecasts
    ]
    conn.executemany("""
        INSERT INTO forecasts (
            id, reference_time, capture_time, latitude, longitude, deleted
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, forecast_rows)

    weather_columns = ", ".join(
        f"{variable} REAL" for variable in weather_variables
    )
    conn.execute(f"""
        CREATE TABLE forecast_values (
            id INTEGER PRIMARY KEY,
            forecast_id INTEGER NOT NULL,
            target_time TEXT NOT NULL,
            {weather_columns},
            FOREIGN KEY (forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE,
            UNIQUE (forecast_id, target_time)
        )
    """)

    selected_columns = ", ".join(
        ['forecast_id', 'target_time', *weather_variables]
    )
    old_values = conn.execute(f"""
        SELECT {selected_columns}
        FROM forecast_values_version_2
        ORDER BY rowid
    """).fetchall()
    value_rows = [
        (
            row[0],
            normalize_database_datetime(row[1], timezone_name),
            *row[2:],
        )
        for row in old_values
    ]
    placeholders = ", ".join('?' for _ in selected_columns.split(', '))
    conn.executemany(f"""
        INSERT INTO forecast_values ({selected_columns})
        VALUES ({placeholders})
    """, value_rows)

    if len(forecast_rows) != conn.execute(
        "SELECT COUNT(*) FROM forecasts"
    ).fetchone()[0]:
        raise RuntimeError("Forecast row count changed during migration")
    if len(value_rows) != conn.execute(
        "SELECT COUNT(*) FROM forecast_values"
    ).fetchone()[0]:
        raise RuntimeError("Forecast value row count changed during migration")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("Foreign-key errors found after timestamp migration")

    conn.execute("DROP TABLE forecast_values_version_2")
    conn.execute("DROP TABLE forecasts_version_2")


MIGRATIONS = {
    1: migrate_to_version_1,
    2: migrate_to_version_2,
    3: migrate_to_version_3,
}


def migrate_database(
    conn: sqlite3.Connection,
    weather_variables: Sequence[str],
    timezone_name: str,
):
    """Apply pending schema migrations in order through the latest version.

    Each version runs in its own transaction and updates ``user_version`` only
    after success. A failure rolls back the current version but preserves any
    earlier versions committed during this call. Newer or incomplete migration
    histories raise ``RuntimeError``.
    """
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    latest_version = max(MIGRATIONS, default=0)

    if current_version > latest_version:
        raise RuntimeError(
            f"Database schema version {current_version} is newer than supported "
            f"version {latest_version}"
        )

    for version in range(current_version + 1, latest_version + 1):
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(f"Missing database migration for version {version}")

        try:
            conn.execute("BEGIN")
            migration(conn, weather_variables, timezone_name)
            conn.execute(f"PRAGMA user_version = {version}")
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
