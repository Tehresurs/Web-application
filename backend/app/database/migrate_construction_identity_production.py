"""Explicitly gated runner for the production construction-identity migration."""

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql


DATABASE = "ai_excel_agent"
SCHEMA = "public"
MIGRATION = Path(__file__).with_name("migrations") / "024_construction_identity_production.sql"
SNAPSHOT_TABLES = (
    "construction_objects",
    "construction_subobjects",
    "employee_assignments",
    "rail_tickets",
    "production_assignment_items",
    "daily_control_results",
)
EXPECTED_SOURCE_COUNTS = {
    "construction_objects": 143,
    "construction_subobjects": 10,
    "employee_assignments": 249,
    "rail_tickets": 125,
    "production_assignment_items": 3,
    "daily_control_results": 420,
}


def connect(*, read_only):
    backend_dir = Path(__file__).resolve().parents[2]
    config = dotenv_values(backend_dir / ".env")
    configured_database = config.get("DB_NAME")
    if configured_database != DATABASE:
        raise RuntimeError(f"Refusing database configured as {configured_database!r}")
    profile = os.getenv("APP_DB_PROFILE", config.get("APP_DB_PROFILE"))
    if profile not in (None, "production"):
        raise RuntimeError("APP_DB_PROFILE must be unset or 'production'")

    options = ["-c search_path=public"]
    if read_only:
        options.append("-c default_transaction_read_only=on")
    return psycopg.connect(
        host=config.get("DB_HOST"),
        port=config.get("DB_PORT"),
        dbname=configured_database,
        user=config.get("DB_USER"),
        password=config.get("DB_PASSWORD"),
        options=" ".join(options),
    )


def verify_target(conn, *, require_writable):
    database, schema, read_only = conn.execute(
        "SELECT current_database(), current_schema(), current_setting('transaction_read_only')"
    ).fetchone()
    if database != DATABASE or schema != SCHEMA:
        raise RuntimeError(f"Refusing target {database}.{schema}; expected {DATABASE}.{SCHEMA}")
    expected_read_only = "off" if require_writable else "on"
    if read_only != expected_read_only:
        raise RuntimeError(
            f"Connection read-only state is {read_only!r}; expected {expected_read_only!r}"
        )


def table_columns(conn, table):
    return {
        row[0]
        for row in conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (SCHEMA, table),
        ).fetchall()
    }


def preflight(conn, *, read_only):
    verify_target(conn, require_writable=not read_only)
    required = {
        "employees": {"id"},
        "construction_objects": {"id", "name", "is_archived", "archived_at", "activity_status"},
        "construction_subobjects": {
            "id", "object_id", "name", "is_active", "is_archived", "archived_at", "activity_status",
        },
        "employee_assignments": {"id", "employee_id", "object_id", "po_id", "category_id"},
        "rail_tickets": {"id", "object_id"},
        "production_assignment_items": {"id", "object_id", "subobject_id", "change_id"},
        "daily_control_results": {
            "id", "report_date", "employee_id", "object_id", "subobject_id",
            "po_id", "subcontractor_id", "category_id",
        },
    }
    for table, columns in required.items():
        actual = table_columns(conn, table)
        if not actual:
            raise RuntimeError(f"Required table is missing: {SCHEMA}.{table}")
        missing = columns - actual
        if missing:
            raise RuntimeError(f"{table} is missing required columns: {sorted(missing)}")
        if "entity_id" in actual:
            raise RuntimeError(f"{table}.entity_id already exists; refusing partial or repeated migration")

    if conn.execute("SELECT to_regclass('construction_entities')").fetchone()[0] is not None:
        raise RuntimeError("construction_entities already exists; refusing partial or repeated migration")
    if conn.execute("SELECT to_regclass('construction_entity_hierarchy')").fetchone()[0] is not None:
        raise RuntimeError("construction_entity_hierarchy already exists; refusing partial or repeated migration")
    if conn.execute("SELECT to_regclass('construction_entity_current')").fetchone()[0] is not None:
        raise RuntimeError("construction_entity_current already exists; refusing partial or repeated migration")
    if conn.execute("SELECT to_regprocedure('normalize_known_value(text,text)')").fetchone()[0] is None:
        raise RuntimeError("normalize_known_value(text,text) is required")

    checks = {
        "orphan_subobjects": """
            SELECT count(*) FROM construction_subobjects s
            LEFT JOIN construction_objects o ON o.id = s.object_id WHERE o.id IS NULL
        """,
        "invalid_employee_assignments": """
            SELECT count(*) FROM employee_assignments a
            LEFT JOIN employees e ON e.id = a.employee_id
            LEFT JOIN construction_objects o ON o.id = a.object_id
            WHERE e.id IS NULL OR o.id IS NULL
        """,
        "invalid_facts": """
            SELECT count(*) FROM daily_control_results f
            LEFT JOIN employees e ON e.id = f.employee_id
            LEFT JOIN construction_objects o ON o.id = f.object_id
            LEFT JOIN construction_subobjects s ON s.id = f.subobject_id
            WHERE e.id IS NULL OR (f.object_id IS NOT NULL AND o.id IS NULL)
               OR (f.subobject_id IS NOT NULL AND s.id IS NULL)
        """,
        "invalid_production_items": """
            SELECT count(*) FROM production_assignment_items i
            LEFT JOIN construction_objects o ON o.id = i.object_id
            LEFT JOIN construction_subobjects s ON s.id = i.subobject_id
            WHERE (i.object_id IS NOT NULL AND o.id IS NULL)
               OR (i.subobject_id IS NOT NULL AND s.id IS NULL)
        """,
        "invalid_ticket_objects": """
            SELECT count(*) FROM rail_tickets t
            LEFT JOIN construction_objects o ON o.id = t.object_id
            WHERE t.object_id IS NOT NULL AND o.id IS NULL
        """,
        "duplicate_normalized_roots": """
            SELECT count(*) FROM (
                SELECT normalize_known_value('object', name) AS n
                FROM construction_objects GROUP BY 1 HAVING count(*) > 1
            ) d
        """,
        "duplicate_normalized_siblings": """
            SELECT count(*) FROM (
                SELECT object_id, normalize_known_value('object', name) AS n
                FROM construction_subobjects GROUP BY 1, 2 HAVING count(*) > 1
            ) d
        """,
        "duplicate_fact_keys": """
            SELECT count(*) FROM (
                SELECT report_date, employee_id, object_id, subobject_id, po_id,
                       subcontractor_id, category_id
                FROM daily_control_results
                GROUP BY 1, 2, 3, 4, 5, 6, 7 HAVING count(*) > 1
            ) d
        """,
    }
    conflicts = {
        name: conn.execute(query).fetchone()[0]
        for name, query in checks.items()
    }
    nonzero = {name: count for name, count in conflicts.items() if count}
    if nonzero:
        raise RuntimeError(f"Production preflight found conflicts: {nonzero}")

    counts = {
        table: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        for table in SNAPSHOT_TABLES
    }
    if counts != EXPECTED_SOURCE_COUNTS:
        raise RuntimeError(
            "Production source counts differ from the approved 4.12.1 baseline; "
            f"expected={EXPECTED_SOURCE_COUNTS}, actual={counts}"
        )
    archive_counts = {
        table: conn.execute(
            sql.SQL(
                "SELECT count(*) FILTER (WHERE is_archived), count(*) FROM {}"
            ).format(sql.Identifier(table))
        ).fetchone()
        for table in ("construction_objects", "construction_subobjects")
    }
    expected_archive_counts = {
        "construction_objects": (1, 143),
        "construction_subobjects": (0, 10),
    }
    if archive_counts != expected_archive_counts:
        raise RuntimeError(
            "Production archive counts differ from the approved 4.12.1 baseline; "
            f"expected={expected_archive_counts}, actual={archive_counts}"
        )
    return {"counts": counts, "archive_counts": archive_counts, "conflicts": conflicts}


def snapshot(conn, columns_by_table=None):
    snapshots = {}
    for table in SNAPSHOT_TABLES:
        columns = (
            columns_by_table[table]
            if columns_by_table is not None
            else sorted(table_columns(conn, table))
        )
        snapshots[table] = conn.execute(
            sql.SQL(
                """
                SELECT jsonb_agg(
                    (SELECT jsonb_object_agg(key, value)
                     FROM jsonb_each(to_jsonb(row_data))
                     WHERE key = ANY(%s))
                    ORDER BY row_data.id
                )
                FROM {} AS row_data
                """
            ).format(sql.Identifier(SCHEMA, table)),
            (columns,),
        ).fetchone()[0]
    return snapshots


def verify_migrated_state(conn, baseline):
    expected_entities = (
        baseline["counts"]["construction_objects"]
        + baseline["counts"]["construction_subobjects"]
    )
    entity_count = conn.execute("SELECT count(*) FROM construction_entities").fetchone()[0]
    hierarchy_count = conn.execute("SELECT count(*) FROM construction_entity_hierarchy").fetchone()[0]
    view_count = conn.execute("SELECT count(*) FROM construction_entity_current").fetchone()[0]
    if (entity_count, hierarchy_count, view_count) != (
        expected_entities, expected_entities, expected_entities
    ):
        raise RuntimeError(
            "Entity counts do not match source rows: "
            f"expected={expected_entities}, actual={(entity_count, hierarchy_count, view_count)}"
        )

    unmapped_objects = conn.execute(
        """
        SELECT count(*) FROM construction_objects o
        LEFT JOIN construction_entities e ON e.legacy_object_id = o.id
        LEFT JOIN construction_entity_hierarchy h ON h.entity_id = e.id
        WHERE e.id IS NULL OR h.entity_id IS NULL OR h.parent_entity_id IS NOT NULL
        """
    ).fetchone()[0]
    invalid_subobjects = conn.execute(
        """
        SELECT count(*) FROM construction_subobjects s
        LEFT JOIN construction_entities e ON e.legacy_subobject_id = s.id
        LEFT JOIN construction_entities p ON p.legacy_object_id = s.object_id
        LEFT JOIN construction_entity_hierarchy h ON h.entity_id = e.id
        WHERE e.id IS NULL OR p.id IS NULL OR h.entity_id IS NULL
           OR h.parent_entity_id IS DISTINCT FROM p.id
        """
    ).fetchone()[0]
    if unmapped_objects or invalid_subobjects:
        raise RuntimeError(
            f"Hierarchy verification failed: unmapped_objects={unmapped_objects}, "
            f"invalid_subobjects={invalid_subobjects}"
        )


def run_migration(conn):
    with conn.transaction():
        verify_target(conn, require_writable=True)
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '10min'")
        conn.execute("SELECT pg_advisory_xact_lock(20261013, 24)")
        for table in SNAPSHOT_TABLES:
            conn.execute(
                sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.Identifier(SCHEMA, table)
                )
            )

        baseline = preflight(conn, read_only=False)
        source_columns = {
            table: sorted(table_columns(conn, table))
            for table in SNAPSHOT_TABLES
        }
        before = snapshot(conn, source_columns)
        conn.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)
        after = snapshot(conn, source_columns)
        if before != after:
            raise RuntimeError("Historical rows changed; rolling back production migration")
        verify_migrated_state(conn, baseline)

    return baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run migration inside a transaction (requires --allow-production)",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Explicitly authorize a write to ai_excel_agent.public",
    )
    args = parser.parse_args()

    if args.apply and not args.allow_production:
        parser.error("--apply is disabled unless --allow-production is also supplied")
    if args.allow_production and not args.apply:
        parser.error("--allow-production is valid only together with --apply")

    with connect(read_only=not args.apply) as conn:
        with conn.transaction():
            baseline = preflight(conn, read_only=not args.apply)
        if not args.apply:
            print("READ-ONLY PREFLIGHT PASSED; no migration was applied.")
            print(f"Baseline counts: {baseline['counts']}")
            print(f"Archived/total: {baseline['archive_counts']}")
            print(f"Conflict checks: {baseline['conflicts']}")
            return

        result = run_migration(conn)
        print("Production migration 024 committed.")
        print(f"Preserved source counts: {result['counts']}")
        print(f"Archived/total: {result['archive_counts']}")


if __name__ == "__main__":
    main()
