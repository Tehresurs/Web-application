"""Read current employee/crew details; never create deployment records."""
from psycopg.rows import dict_row
from app.database.db import get_connection


def employee_details(ids):
    if not ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('''SELECT e.id, e.phone, p.report_description, p.equipment_description,
                c.vehicle_make, c.vehicle_plate, c.driver_full_name, c.driver_phone
                FROM employees e LEFT JOIN positions p ON p.id=e.position_id
                LEFT JOIN crews c ON c.id=e.crew_id WHERE e.id=ANY(%s)''', (ids,))
            return {row['id']: dict(row) for row in cur.fetchall()}
