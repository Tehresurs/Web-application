"""Explicit migration: python -m app.database.migrate_luvr_history."""
from pathlib import Path

from app.database.db import get_connection


def apply_migration(conn):
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='60s'")
        conn.execute("SELECT pg_advisory_xact_lock(20261002,6)")
        conn.execute((Path(__file__).with_name("migrations") / "006_luvr_history.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    with get_connection() as connection:
        apply_migration(connection)
    print("Migration 006_luvr_history applied successfully")
