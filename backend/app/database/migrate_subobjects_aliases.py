"""Explicit migration: python -m app.database.migrate_subobjects_aliases."""
from pathlib import Path

from app.database.db import get_connection


def apply_migration(conn):
    migration = Path(__file__).with_name("migrations") / "002_subobjects_aliases.sql"
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute("SELECT pg_advisory_xact_lock(20260928, 2)")
        for table in ("employees", "construction_objects", "po_types", "object_categories",
                      "employee_assignments", "daily_control_results"):
            cursor.execute("SELECT to_regclass(%s)", (table,))
            if cursor.fetchone()[0] is None:
                raise RuntimeError(f"Missing prerequisite table: {table}")
        cursor.execute(migration.read_text(encoding="utf-8"))


def main():
    with get_connection() as conn:
        apply_migration(conn)
    print("Migration 002_subobjects_aliases applied successfully")


if __name__ == "__main__":
    main()
