import os
import sqlite3
from collections.abc import Sequence

from src.database_migrations import migrate_database
from src.time_utils import normalize_database_datetime


class Database:
    def __init__(
        self,
        db_path: str,
        timezone_name: str,
        read_only: bool = False,
        weather_variables: Sequence[str] | None = None,
    ):
        """Open and configure the application-owned SQLite connection.

        ``weather_variables`` is required. The database parent directory is
        created if needed, while read-only mode requires an existing database.
        Call ``close`` when the connection is no longer needed.
        """
        self.db_path = db_path
        if weather_variables is None:
            raise ValueError("weather_variables is required")
        self.weather_variables = list(weather_variables)
        self.timezone_name = timezone_name
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
         
        if read_only:
            self.conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        else:
            self.conn = sqlite3.connect(self.db_path)

        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def init_db(self):
        migrate_database(
            self.conn,
            self.weather_variables,
            self.timezone_name,
        )

    def save_forecast(
        self,
        reference_time: str,
        capture_time: str,
        lat: float,
        lon: float,
        forecast_records: list[dict],
    ):
        """Atomically save a forecast and its timestamped values.

        Every record must contain ``timestamp``; absent configured weather
        variables are stored as null. All timestamps must include an offset and
        are normalized to UTC.
        """
        reference_time = normalize_database_datetime(reference_time)
        capture_time = normalize_database_datetime(capture_time)

        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO forecasts "
                "(reference_time, capture_time, latitude, longitude) "
                "VALUES (?, ?, ?, ?)",
                (reference_time, capture_time, lat, lon)
            )
            forecast_id = cursor.lastrowid

            values_to_insert = [
                (
                    forecast_id,
                    normalize_database_datetime(record['timestamp']),
                    *(record.get(var) for var in self.weather_variables),
                )
                for record in forecast_records
            ]

            placeholders = ", ".join(["?"] * (2 + len(self.weather_variables)))
            columns = "forecast_id, target_time, " + ", ".join(self.weather_variables)

            self.conn.executemany(
                f"INSERT INTO forecast_values ({columns}) VALUES ({placeholders})",
                values_to_insert
            )

    def close(self):
        self.conn.close()

    def get_all_forecasts(self) -> list[sqlite3.Row]:
        """Retrieves all forecasts and their values for analysis."""
        # Create a SELECT statement that includes all weather variables
        columns = ", ".join([f"fv.{var}" for var in self.weather_variables])
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT f.id, f.reference_time, fv.target_time, {columns}
            FROM forecasts f
            JOIN forecast_values fv ON f.id = fv.forecast_id
            WHERE f.deleted = 0
            ORDER BY f.reference_time, fv.target_time
        """)
        return cursor.fetchall()
