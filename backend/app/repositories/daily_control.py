from app.database.db import get_connection


def find_assignment(cursor, employee_id, object_id, po_id, assignment_id=None):
    """Hold the assignment stable until validation/save transaction completes."""
    cursor.execute(
        """SELECT ea.id, ea.employee_id, ea.object_id, ea.po_id, ea.category_id
           FROM employee_assignments ea
           JOIN employees e ON e.id = ea.employee_id
           JOIN construction_objects o ON o.id = ea.object_id
           JOIN po_types p ON p.id = ea.po_id
           JOIN object_categories c ON c.id = ea.category_id
           WHERE ea.employee_id = %s AND ea.object_id = %s AND ea.po_id = %s
             AND (%s::bigint IS NULL OR ea.id = %s)
           ORDER BY ea.id FOR SHARE OF ea, e, o, p, c""",
        (employee_id, object_id, po_id, assignment_id, assignment_id),
    )
    return [dict(zip(("assignment_id", "employee_id", "object_id", "po_id", "category_id"), row))
            for row in cursor.fetchall()]


_FACT_SELECT = """SELECT r.id, r.report_date, r.employee_id, e.full_name, r.object_id,
    r.subobject_id, CASE WHEN r.subobject_id IS NULL THEN o.name ELSE s.name END,
    CASE WHEN r.subobject_id IS NULL THEN 'object' ELSE 'subobject' END,
    r.po_id, r.category_id, r.source_file, r.subcontractor_id, sc.name
    FROM daily_control_results r
    JOIN employees e ON e.id = r.employee_id
    JOIN construction_objects o ON o.id = r.object_id
    LEFT JOIN construction_subobjects s ON s.id = r.subobject_id
    LEFT JOIN po_types sc ON sc.id = r.subcontractor_id"""
_FACT_FIELDS = ("id", "report_date", "employee_id", "employee_name", "object_id", "subobject_id",
                "control_item_name", "control_item_type", "po_id", "category_id", "source_file", "subcontractor_id", "subcontractor_name")


def saved_source(cursor, digest):
    cursor.execute(_FACT_SELECT + " WHERE r.source_sha256 = %s ORDER BY r.id", (digest,))
    return [dict(zip(_FACT_FIELDS, row)) for row in cursor.fetchall()]


def get_control_fact(cursor, fact_id):
    cursor.execute(_FACT_SELECT + " WHERE r.id = %s", (fact_id,))
    return dict(zip(_FACT_FIELDS, cursor.fetchone()))


def insert_fact(cursor, report_date, assignment, source_file, digest):
    if assignment.get("subobject_id") is not None:
        cursor.execute("SELECT object_id, is_active FROM construction_subobjects WHERE id = %s FOR SHARE",
                       (assignment["subobject_id"],))
        child = cursor.fetchone()
        if child is None or not child[1] or child[0] != assignment["object_id"]:
            raise ValueError("Подобъект не найден, неактивен или не принадлежит выбранному объекту")
    key = (report_date, assignment["employee_id"], assignment["object_id"],
           assignment["po_id"], assignment["category_id"])
    cursor.execute(
        """INSERT INTO daily_control_results
           (report_date, employee_id, object_id, po_id, category_id, source_file, source_sha256, subobject_id, subcontractor_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT ON CONSTRAINT uq_daily_control_fact DO NOTHING RETURNING id""",
        (*key, source_file, digest, assignment.get("subobject_id"), assignment.get("subcontractor_id")),
    )
    row = cursor.fetchone()
    if row:
        return {**get_control_fact(cursor, row[0]), "created": True}
    cursor.execute(
        """SELECT id, subobject_id FROM daily_control_results WHERE report_date = %s
           AND employee_id = %s AND object_id = %s AND po_id = %s AND category_id = %s
           AND subobject_id IS NOT DISTINCT FROM %s
           AND subcontractor_id IS NOT DISTINCT FROM %s""",
        (*key, assignment.get("subobject_id"), assignment.get("subcontractor_id")),
    )
    existing = cursor.fetchone()
    return {**get_control_fact(cursor, existing[0]), "created": False}


def _journal_filter(date_from, date_to, employee_id=None, object_id=None,
                    subobject_id=None, include_subobjects=True, subcontractor_id=None):
    clauses = ["r.report_date BETWEEN %s AND %s"]
    params = [date_from, date_to]
    if employee_id is not None:
        clauses.append("r.employee_id = %s")
        params.append(employee_id)
    if object_id is not None:
        clauses.append("r.object_id = %s")
        params.append(object_id)
        if subobject_id is None and not include_subobjects:
            clauses.append("r.subobject_id IS NULL")
    if subobject_id is not None:
        clauses.append("r.subobject_id = %s")
        params.append(subobject_id)
    if subcontractor_id is not None:
        clauses.append("r.subcontractor_id = %s")
        params.append(subcontractor_id)
    return " AND ".join(clauses), params


def _journal_options(cursor, date_from, date_to):
    # Return distinct directory choices, never all unfiltered facts to the browser.
    cursor.execute("""SELECT DISTINCT e.id, e.full_name
        FROM daily_control_results r JOIN employees e ON e.id = r.employee_id
        WHERE r.report_date BETWEEN %s AND %s ORDER BY e.full_name, e.id""", (date_from, date_to))
    employees = [{"employee_id": row[0], "full_name": row[1]} for row in cursor.fetchall()]
    cursor.execute("""WITH positions AS (
        SELECT DISTINCT object_id, subobject_id FROM daily_control_results
        WHERE report_date BETWEEN %s AND %s
    )
    SELECT DISTINCT 'object:' || o.id, 'object', o.id, NULL::bigint, o.name, o.name
        FROM positions r JOIN construction_objects o ON o.id = r.object_id
    UNION
    SELECT 'subobject:' || s.id, 'subobject', o.id, s.id, s.name, o.name
        FROM positions r JOIN construction_subobjects s ON s.id = r.subobject_id
        JOIN construction_objects o ON o.id = r.object_id
    ORDER BY 6, 2, 5, 1""", (date_from, date_to))
    fields = ("control_item_key", "control_item_type", "object_id", "subobject_id", "control_item_name", "object_name")
    control_items = [dict(zip(fields, row)) for row in cursor.fetchall()]
    cursor.execute("""SELECT DISTINCT p.id, p.name FROM daily_control_results r
        JOIN po_types p ON p.id = r.subcontractor_id
        WHERE r.report_date BETWEEN %s AND %s ORDER BY p.name, p.id""", (date_from, date_to))
    return {"employees": employees, "control_items": control_items,
            "subcontractors": [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]}


def get_journal(date_from, date_to, employee_id=None, object_id=None, view="object",
                *, subobject_id=None, include_subobjects=True, subcontractor_id=None):
    where, params = _journal_filter(date_from, date_to, employee_id, object_id,
                                    subobject_id, include_subobjects, subcontractor_id)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT r.id, r.report_date, r.employee_id, e.full_name,
                          r.object_id, o.name, r.po_id, p.name,
                          r.category_id, c.name, r.source_file, r.created_at, r.subobject_id, s.name, r.subcontractor_id, sc.name
                   FROM daily_control_results r
                   JOIN employees e ON e.id = r.employee_id
                   JOIN construction_objects o ON o.id = r.object_id
                   JOIN po_types p ON p.id = r.po_id
                   JOIN object_categories c ON c.id = r.category_id
                   LEFT JOIN construction_subobjects s ON s.id = r.subobject_id
                   LEFT JOIN po_types sc ON sc.id = r.subcontractor_id
                   WHERE """ + where + " ORDER BY r.report_date, r.id", params,
            )
            columns = ("id", "report_date", "employee_id", "full_name", "object_id",
                       "object_name", "po_id", "po_name", "category_id", "category_name",
                       "source_file", "created_at", "subobject_id", "subobject_name", "subcontractor_id", "subcontractor_name")
            items = [dict(zip(columns, row)) for row in cursor.fetchall()]
            options = _journal_options(cursor, date_from, date_to)
    return {**summarize_journal(items, view), "options": options}


def _control_item(item):
    child = item.get("subobject_id") is not None
    kind = "subobject" if child else "object"
    return {"control_item_type": kind,
            "control_item_key": f"{kind}:{item['subobject_id'] if child else item['object_id']}",
            "control_item_name": item.get("subobject_name") if child else item["object_name"]}


def _journal_summary(items):
    return {
        "facts_count": len(items),
        "objects_count": len({item["object_id"] for item in items}),
        "subobjects_count": len({item["subobject_id"] for item in items if item.get("subobject_id") is not None}),
        "employees_count": len({item["employee_id"] for item in items}),
        "days_count": len({item["report_date"] for item in items}),
    }


def summarize_journal(items, view):
    items = [{**item, **_control_item(item)} for item in items]
    pairs = {}
    for item in items:
        key = (item["control_item_key"], item["employee_id"])
        pair = pairs.setdefault(key, {
            "object_id": item["object_id"], "object_name": item["object_name"],
            "subobject_id": item.get("subobject_id"), "subobject_name": item.get("subobject_name"),
            **_control_item(item),
            "employee_id": item["employee_id"], "full_name": item["full_name"],
            "dates": set(), "fact_ids": [],
        })
        pair["dates"].add(item["report_date"])
        pair["fact_ids"].append(item["id"])
    groups = {}
    primary = "control_item_key" if view == "object" else "employee_id"
    name = "control_item_name" if view == "object" else "full_name"
    for pair in pairs.values():
        pair["dates"] = sorted(pair["dates"])
        pair["days_count"] = len(pair["dates"])
        metadata = {k: pair[k] for k in ("object_id", "object_name", "subobject_id", "subobject_name",
                                        "control_item_key", "control_item_name", "control_item_type")} if view == "object" else {"employee_id": pair["employee_id"], "full_name": pair["full_name"]}
        group = groups.setdefault(pair[primary], {**metadata, "items": []})
        group["items"].append(pair)
    for group in groups.values():
        group["items"].sort(key=lambda item: (item["full_name"].lower(), (item["control_item_name"] or "").lower(), item["control_item_key"]))
        group["dates"] = sorted({day for pair in group["items"] for day in pair["dates"]})
        group["days_count"] = len(group["dates"])
    return {
        "items": items,
        "groups": sorted(groups.values(), key=lambda group: ((group[name] or "").lower(), str(group[primary]))),
        "summary": _journal_summary(items),
        "dates": sorted({item["report_date"] for item in items}),
    }
