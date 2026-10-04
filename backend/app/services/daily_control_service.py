import logging
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from typing import Literal

from app.database.db import get_connection
from app.parsers.word_parser import read_document
from app.services.processing_service import prepare_report
from app.services.report_dates import parsed_date
from app.services.po_matcher import subcontractor_is_absent
from app.repositories.daily_control import find_assignment, insert_fact, saved_source


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    # Explicit selections resolve similar/new entities; dates/statuses are never supplied by UI.
    employee_id: PositiveInt | None = None
    object_id: PositiveInt | None = None
    subobject_id: PositiveInt | None = None
    general_contractor_id: PositiveInt | None = None
    subcontractor_id: PositiveInt | None = None
    assignments: dict[PositiveInt, PositiveInt] = Field(default_factory=dict)
    unresolved_aliases: list[Literal["employee", "object", "general_contractor", "subcontractor"]] = Field(default_factory=list)


def validate_review(cursor, document, report, request):
    data = document["business_data"]
    problems = []
    if request.unresolved_aliases:
        problems.append("Есть несогласованное или ещё сохраняемое соответствие alias")
    for key, label in (("report_date", "Дата"), ("inspector", "ФИО"),
                       ("object", "Объект"), ("general_contractor", "Генподрядчик")):
        if not data[key]["found"]:
            problems.append(f"{label}: обязательное поле не распознано")
    report_date = parsed_date(data["report_date"].get("value"))
    if report_date is None:
        problems.append("Дата отчёта некорректна")

    def resolved(id_key, status_key, label):
        selected = getattr(request, id_key)
        value = selected or (report.get(id_key) if report.get(status_key) == "found" else None)
        if not value:
            problems.append(f"{label}: требуется окончательное сопоставление")
        return value

    employee_id = resolved("employee_id", "employee_status", "Инженер")
    object_id = resolved("object_id", "object_status", "Объект")
    # Explicit null clears an automatically matched subobject; an omitted field
    # retains it unless the caller explicitly selected another parent object.
    subobject_id = (request.subobject_id if "subobject_id" in request.model_fields_set
                    else report.get("subobject_id") if request.object_id in (None, report.get("object_id")) else None)
    if subobject_id is not None:
        cursor.execute("SELECT object_id, is_active FROM construction_subobjects WHERE id = %s FOR SHARE", (subobject_id,))
        child = cursor.fetchone()
        if child is None or not child[1]:
            problems.append("Подобъект не найден или неактивен")
        elif child[0] != object_id:
            problems.append("Подобъект не принадлежит выбранному объекту")
        elif "subobject_id" in request.model_fields_set:
            logging.getLogger(__name__).info("SUBOBJECT_SELECTED: subobject_id=%s object_id=%s", subobject_id, object_id)
    po_ids = [resolved("general_contractor_id", "general_contractor_status", "Генподрядчик")]
    subcontractor_id = None
    source_subcontractor = data["subcontractor"]
    if source_subcontractor["found"] and not subcontractor_is_absent(source_subcontractor.get("raw", source_subcontractor.get("value"))):
        subcontractor_id = resolved("subcontractor_id", "subcontractor_status", "Субподрядчик")
        if subcontractor_id is not None:
            cursor.execute("SELECT id FROM po_types WHERE id = %s FOR SHARE", (subcontractor_id,))
            if cursor.fetchone() is None:
                problems.append("Субподрядчик не найден в справочнике организаций")
            elif request.subcontractor_id is not None:
                logging.getLogger(__name__).info("SUBCONTRACTOR_SELECTED: target_id=%s", subcontractor_id)
    elif request.subcontractor_id is not None:
        problems.append("Субподрядчик отсутствует в исходном отчёте")

    facts = []
    unique_po_ids = {po_id for po_id in po_ids if po_id}
    if set(request.assignments) - unique_po_ids:
        problems.append("Выбрано назначение для ПО, отсутствующего в отчёте")
    for po_id in sorted(unique_po_ids):
        if not employee_id or not object_id:
            continue
        matches = find_assignment(cursor, employee_id, object_id, po_id, request.assignments.get(po_id))
        if len(matches) != 1:
            problems.append(f"ПО {po_id}: выберите одно действующее назначение с категорией")
        else:
            fact = {**matches[0], "subobject_id": subobject_id, "subcontractor_id": subcontractor_id}
            facts.append(fact)
    return {
        "can_save": not problems and bool(facts), "saved": False,
        "report_date": report_date, "source_file": document["filename"],
        "problems": problems, "facts": facts,
    }


def review_result(request: ReviewRequest, *, save=False):
    path = Path(request.path)
    if path.suffix.lower() != ".docx" or not path.is_file():
        raise ValueError("Укажите существующий Word-отчёт .docx")
    content = path.read_bytes()
    digest = sha256(content).hexdigest()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if save:
                # Serialize saves of this source; the unique fact constraint also protects
                # against a renamed/repacked copy submitted concurrently.
                cursor.execute("SELECT pg_advisory_xact_lock(%s)",
                               (int.from_bytes(bytes.fromhex(digest)[:8], signed=True),))
            previous = saved_source(cursor, digest)
            if previous:
                return {"can_save": False, "saved": True, "created": False,
                        "report_date": previous[0]["report_date"], "source_file": path.name,
                        "problems": [], "results": [{**row, "created": False} for row in previous]}

            # Both hash and parser use exactly the same immutable bytes.
            source = BytesIO(content)
            source.name = path.name
            document = read_document(source)
            report = prepare_report(document)
            result = validate_review(cursor, document, report, request)
            if save and result["can_save"]:
                result["results"] = [
                    insert_fact(cursor, result["report_date"], fact, path.name, digest)
                    for fact in result["facts"]
                ]
                result.update(saved=True, can_save=False,
                              created=any(item["created"] for item in result["results"]))
            return result
