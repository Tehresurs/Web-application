"""Explicit, additive migration: python -m app.database.migrate_daily_control."""
from pathlib import Path

from app.database.db import get_connection


def main():
    migration = Path(__file__).with_name("migrations") / "001_daily_control_results.sql"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for table in ("employees", "construction_objects", "po_types",
                          "object_categories", "employee_assignments"):
                cursor.execute("SELECT to_regclass(%s)", (table,))
                if cursor.fetchone()[0] is None:
                    raise RuntimeError(f"Отсутствует обязательная таблица {table}")
            cursor.execute(migration.read_text(encoding="utf-8"))
    print("Миграция daily_control_results применена")


if __name__ == "__main__":
    main()
