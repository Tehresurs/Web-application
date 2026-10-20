"""B2 only: consume ready matrix cells with FACT priority; no allocation, Excel or writes."""
from calendar import monthrange
from collections import Counter
from datetime import date

MAIN_POSITION_ORDER = (2, 3, 4, 5, 7, 9)
OTHER_POSITION_ORDER = (16, 7, 11, 12, 13, 15, 10)
# Explicitly approved report-only additions, scoped to their subsections.
ADDITIONAL_POSITION_ORDER = {"6.2": (3,), "6.4": (6, 8, 14, 20)}


def position_order(section_code):
    if section_code.startswith("6."):
        return OTHER_POSITION_ORDER + ADDITIONAL_POSITION_ORDER.get(section_code, ())
    return MAIN_POSITION_ORDER

EXCLUDED_POSITION_ID = 17
SUBSECTIONS = (("6.1", 7, "Инженерные изыскания"),
               ("6.2", 8, "Проведение технической аттестации МТР"),
               ("6.3", 9, "Специалист ОТ ПБ (100% контроль РПО)"),
               ("6.4", None, "Прочие"))


class VouDataError(ValueError):
    def __init__(self, code, **details):
        self.code, self.details = code, details
        super().__init__(f"{code}: {details}")


def _fail(code, **details):
    raise VouDataError(code, **details)


def _fio(value):
    return " ".join(value.split()).casefold().replace("ё", "е")


def distribution_key(display_row, cell):
    """Match a matrix allocation lane, not an entire employee/day or category.

    Native matrix row_key includes object, PO, subcontractor and simultaneous
    occurrence. Category may change with a dated correction, so is not identity.
    """
    if display_row.get("row_key"):
        return ("matrix_row", display_row["row_key"])
    obj = (("entity", cell["entity_id"]) if cell.get("entity_id") is not None
           else ("legacy", cell.get("object_id"), cell.get("subobject_id")))
    return (cell.get("kind"), obj, cell.get("po_id"), cell.get("subcontractor_id"))


def select_matrix_cells(matrix, confirmed_facts):
    """Select existing values only. Zero FACT and DK also supersede PLAN.

    Never fall back from a corrupt FACT-labelled cell: inconsistent provenance
    is an error, not permission to invent a different matrix allocation.
    """
    year, month = matrix["year"], matrix["month"]
    valid_days = {date(year, month, d).isoformat() for d in range(1, monthrange(year, month)[1]+1)}
    confirmed = {f["id"]: f for f in confirmed_facts}
    records, factual_keys, seen = [], set(), set()
    counts, sums = Counter(), Counter()
    for employee in matrix["employees"]:
        eid = employee["employee_id"]
        for row in employee["rows"]:
            for day, cell in row["cells"].items():
                source, cents = cell.get("source"), cell.get("share_cents")
                if source not in ("FACT", "PLAN"):
                    _fail("UNKNOWN_MATRIX_SOURCE", source=source)
                if type(cents) is not int or cents < 0:
                    _fail("INVALID_MATRIX_SHARE", employee_id=eid, date=day)
                if day not in valid_days or cell.get("date") != day or cell.get("employee_id") != eid:
                    _fail("MATRIX_CELL_IDENTITY_MISMATCH", employee_id=eid, date=day)
                key = (eid, day, distribution_key(row, cell))
                counts[source] += 1
                sums[source] += cents
                if source == "FACT":
                    fid = cell.get("source_fact_id")
                    fact = confirmed.get(fid)
                    if (not fact or fact.get("employee_id") != eid or str(fact.get("report_date")) != day
                            or cell.get("report_received") is not True):
                        _fail("UNCONFIRMED_OR_STALE_FACT", fact_id=fid, employee_id=eid, date=day)
                    if (eid, day, fid) in seen:
                        _fail("DUPLICATE_MATRIX_FACT", fact_id=fid, employee_id=eid, date=day)
                    seen.add((eid, day, fid))
                    if cell.get("category_id") != fact.get("category_id") and not (cell.get("applied_overrides") or {}).get("CATEGORY"):
                        _fail("FACT_CATEGORY_MISMATCH", fact_id=fid, date=day)
                    factual_keys.add(key)
                records.append((key, employee, row, day, cell))
    selected, plans_seen = [], set()
    for key, employee, row, day, cell in records:
        source = cell["source"]
        if source == "PLAN" and key in factual_keys:
            counts["superseded_plan"] += 1
            sums["superseded_plan"] += cell["share_cents"]
            continue
        if source == "PLAN":
            if key in plans_seen:
                _fail("DUPLICATE_MATRIX_PLAN", employee_id=employee["employee_id"], date=day)
            plans_seen.add(key)
        selected.append((employee, row, day, cell))
        counts["selected_"+source] += 1
        sums["selected_"+source] += cell["share_cents"]
    return selected, counts, sums


def prepare_data(matrix, positions, categories, confirmed_facts):
    """Pure projection. Fail closed on ambiguous identity/category/provenance.

    Positions/descriptions are the requested directory values; categories come
    ONLY from each dated matrix cell (including its existing dated correction).
    Cameral work without an object belongs to report subsection 6.4 only.
    Unmapped object rows are diagnostic exclusions, never silently remapped.
    """
    year, month = matrix["year"], matrix["month"]
    first = date(year, month, 1)
    days = [date(year, month, d).isoformat() for d in range(1, monthrange(year, month)[1]+1)]
    if not matrix.get("formed"):
        _fail("MATRIX_MONTH_NOT_FORMED", year=year, month=month)
    positions = {p["id"]: p for p in positions}
    catalog = {c["id"]: c for c in categories}
    for cid in range(1, 7):
        if cid not in catalog or catalog[cid].get("parent_id") is not None:
            _fail("CATEGORY_LAYOUT_CHANGED", category_id=cid)
    for cid in (7, 8, 9):
        if cid not in catalog or catalog[cid].get("parent_id") != 6:
            _fail("SUBCATEGORY_LAYOUT_CHANGED", category_id=cid)
    fourth = [c["id"] for c in categories if c.get("parent_id") == 6 and c.get("sort_order") == 4]
    if len(fourth) > 1:
        _fail("AMBIGUOUS_SUBCATEGORY_6_4", ids=fourth)
    fourth_id = fourth[0] if fourth else None
    if fourth_id in (7, 8, 9):
        _fail("SUBCATEGORY_LAYOUT_CHANGED", category_id=fourth_id)
    warnings = []
    if fourth_id is None:
        warnings.append(dict(code="SUBCATEGORY_6_4_NOT_IN_DIRECTORY", subsection="6.4",
                             message="Подраздел 6.4 используется для камеральной работы только в ВОУ; запись справочника не создавалась."))
    subsections = [dict(code=code, category_id=(fourth_id if code == "6.4" else cid),
                        name=name, rows=[]) for code, cid, name in SUBSECTIONS]
    sections = [dict(code=str(cid), category_id=cid, name=catalog[cid]["name"], rows=[])
                for cid in range(1, 6)]
    sections.append(dict(code="6", category_id=6, name="Прочие", subsections=subsections))
    targets = {s["category_id"]: s for s in sections[:5]}
    targets.update({s["category_id"]: s for s in subsections if s["category_id"] is not None})
    targets["CAMERAL_6_4"] = subsections[3]
    selected, counts, sums = select_matrix_cells(matrix, confirmed_facts)
    confirmed = {f["id"]: f for f in confirmed_facts}
    grouped, missing_descriptions = {}, set()
    source_warnings = Counter()
    for employee, display_row, day, cell in selected:
        eid, pid = employee["employee_id"], cell.get("position_id",employee.get("position_id"))
        source, cents = cell["source"], cell["share_cents"]
        fact_id = cell.get("source_fact_id") if source == "FACT" else None
        fact = confirmed.get(fact_id)
        category = cell.get("category_id")
        applied = cell.get("applied_overrides") or {}
        if pid == EXCLUDED_POSITION_ID:
            counts["excluded_position"] += 1
            sums["excluded_position"] += cents
            continue
        if cell.get("is_dk") or cell.get("excluded_from_production"):
            counts["excluded_dk"] += 1
            sums["excluded_dk"] += cents
            continue
        cameral = cell.get("kind") == "CAMERAL" and not cell.get("entity_id") and not cell.get("object_id")
        grouping_category = "CAMERAL_6_4" if cameral else category
        if not cameral and cell.get("kind") != "OBJECT":
            _fail("UNMAPPED_MATRIX_KIND", kind=cell.get("kind"), employee_id=eid, date=day, source=source)
        if not cameral and category not in targets:
            warnings.append(dict(code="OBJECT_CATEGORY_MISSING_OR_UNMAPPED", employee_id=eid,
                full_name=employee["full_name"], date=day, object_name=cell.get("object_name"),
                subobject_name=cell.get("subobject_name"), entity_id=cell.get("entity_id"),
                object_id=cell.get("object_id"), category_id=category, share_cents=cents, source=source,
                message="Строка не включена в разделы ВОУ: категория отсутствует или не сопоставлена."))
            counts["excluded_unmapped_category"] += 1
            sums["excluded_unmapped_category"] += cents
            continue
        target = targets[grouping_category]
        order = position_order(target["code"])
        if pid not in positions or pid not in order:
            _fail("POSITION_ORDER_NOT_AGREED", position_id=pid, category_id=category, fact_id=fact_id,
                  subsection=target["code"], employee_id=eid, full_name=employee["full_name"],
                  position_name=positions.get(pid, {}).get("name"), date=day)
        version_id=cell.get('position_definition_version_id')
        definition=positions[pid] if version_id is None else positions[pid].get('_definitions',{}).get(version_id)
        if definition is None:_fail('POSITION_DEFINITION_VERSION_MISSING',position_id=pid,version_id=version_id,date=day)
        description = definition.get('aos_description')
        if not description or not description.strip():
            description = None
            missing_descriptions.add(pid)
        oid, sid = cell.get("object_id"), cell.get("subobject_id")
        entity = cell.get("entity_id")
        if not cameral and entity is None and oid is None:
            _fail("MISSING_OBJECT_IDENTITY", fact_id=fact_id)
        row_key = (grouping_category, eid, pid, distribution_key(display_row, cell), description)
        row = grouped.setdefault(row_key, dict(employee_id=eid, full_name=employee["full_name"],
            matrix_row_key=display_row.get("row_key"),
            position_id=pid, position_name=cell.get("position_name",positions[pid]["name"]), category_id=category,
            report_section="6" if cameral else target["code"].split(".")[0],
            report_subsection=target["code"] if target["code"].startswith("6.") else None,kind=cell["kind"],
            object_id=oid, subobject_id=sid, entity_id=entity,
            po_id=cell.get("po_id"), subcontractor_id=cell.get("subcontractor_id"),
            object_name=cell.get("object_name"), subobject_name=cell.get("subobject_name"),
            aos_description=description, days_cents={d: 0 for d in days}, sources=[]))
        row["days_cents"][day] += cents
        row["sources"].append(dict(date=day, source=source, fact_id=fact_id,
            assignment_item_id=cell.get("assignment_item_id"),
            basis_fact_id=cell.get("source_fact_id"), share_cents=cents,
            confirmed_category_id=fact.get("category_id") if fact else None,
            matrix_category_id=category, po_id=cell.get("po_id"),control_mode=cell.get("control_mode"),
            subcontractor_id=cell.get("subcontractor_id"),applied_overrides=dict(applied)))
        counts["included"] += 1
        sums["included"] += cents
        counts["included_"+source] += 1
        sums["included_"+source] += cents
        source_warnings.update(cell.get("warnings", []))
    for (category, _, _, _, _), row in grouped.items():
        row["total_cents"] = sum(row["days_cents"].values())
        targets[category]["rows"].append(row)
    def total(container, rows):
        container["days_cents"] = {d: sum(r["days_cents"][d] for r in rows) for d in days}
        container["total_cents"] = sum(container["days_cents"].values())
    for target in sections[:5] + subsections:
        order = position_order(target["code"])
        target["rows"].sort(key=lambda r: (order.index(r["position_id"]), _fio(r["full_name"]),
            r["employee_id"], r.get("entity_id") or 0, r.get("object_id") or 0, r.get("subobject_id") or 0))
    # Include empty categories and the virtual report-only subsection 6.4.
    for target in sections[:5] + subsections:
        total(target, target["rows"])
    total(sections[5], subsections)
    result = dict(year=year, month=month, date_from=first.isoformat(), date_to=days[-1],
                  time_unit="hundredth_of_workday", sections=sections, warnings=warnings,
                  counts=dict(counts), control_cents=dict(sums), matrix_warnings=dict(source_warnings))
    total(result, sections)
    if result["total_cents"] != sums["included"]:
        _fail("CONTROL_TOTAL_MISMATCH")
    for pid in sorted(missing_descriptions):
        warnings.append(dict(code="MISSING_AOS_DESCRIPTION", position_id=pid,
                             position_name=positions[pid]["name"]))
    # No shifts/AL field is produced at any level.
    return result


def prepare_month(year, month, *, with_context=False):
    """Read-only adapter to the existing matrix; no alternative allocation code."""
    # Validate calendar input before opening a connection.
    first = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    from app.services.production_matrix import calculate_month
    from app.database.db import get_connection
    from psycopg.rows import dict_row
    with get_connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        actual=conn.execute('SELECT current_database(),current_schema()').fetchone()
        if actual != ('ai_excel_agent_test','test_construction_identity_stage46'):
            _fail('VOU_WRONG_DATABASE_PROFILE', database=actual[0],schema=actual[1])
        matrix = calculate_month(year, month, connection=conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id,name,aos_description FROM positions ORDER BY id")
            positions = cur.fetchall()
            if conn.execute("SELECT to_regclass('personnel_position_definitions')").fetchone()[0]:
                cur.execute('SELECT id,position_id,definition FROM personnel_position_definitions')
                versions=cur.fetchall()
                for position in positions:position['_definitions']={v['id']:v['definition'] for v in versions if v['position_id']==position['id']}
            cur.execute("SELECT id,name,parent_id,sort_order FROM object_categories ORDER BY id")
            categories = cur.fetchall()
            cur.execute("SELECT id,employee_id,report_date,category_id FROM daily_control_results WHERE report_date BETWEEN %s AND %s", (first, end))
            facts = cur.fetchall()
    report = prepare_data(matrix, positions, categories, facts)
    # B3 may retain display-only empty DK rows from this same read-only snapshot.
    return (report, dict(matrix=matrix, positions=positions)) if with_context else report
