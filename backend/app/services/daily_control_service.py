import logging
from datetime import date
from app.repositories.directory_errors import DirectoryConflict
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
from app.repositories import construction_identity as identity


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    # Explicit selections resolve similar/new entities; dates/statuses are never supplied by UI.
    employee_id: PositiveInt | None = None
    object_id: PositiveInt | None = None
    subobject_id: PositiveInt | None = None
    entity_id: PositiveInt | None = None
    general_contractor_id: PositiveInt | None = None
    subcontractor_id: PositiveInt | None = None
    assignments: dict[PositiveInt, PositiveInt] = Field(default_factory=dict)
    absence_assignment_id: PositiveInt | None = None
    expected_employee_id: PositiveInt | None = None
    expected_report_date: date | None = None
    replace_fact_id: PositiveInt | None = None
    confirm_replacement: bool = False
    replacement_token: str | None = None
    replace_source_sha256: str | None = None
    unresolved_aliases: list[Literal["employee", "object", "general_contractor", "subcontractor"]] = Field(default_factory=list)


def validate_review(cursor, document, report, request, absence=None):
    data = document["business_data"]
    fields=(absence or {}).get('fields',{})
    po_absent=fields.get('general_contractor',{}).get('approved',False)
    problems = []
    if request.unresolved_aliases:
        problems.append("Есть несогласованное или ещё сохраняемое соответствие alias")
    for key, label in (("report_date", "Дата"), ("inspector", "ФИО"),
                       ("object", "Объект"), ("general_contractor", "Генподрядчик")):
        if key=='general_contractor' and po_absent: continue
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
    identities=identity.enabled(cursor.connection)
    entity=None
    entity_id=request.entity_id or (report.get('entity_id') if request.object_id is None and request.subobject_id is None else None)
    if entity_id is not None and not identities:raise ValueError('entity_id пока недоступен')
    object_id = (request.object_id if entity_id is not None else resolved("object_id", "object_status", "Объект"))
    # Explicit null clears an automatically matched subobject; an omitted field
    # retains it unless the caller explicitly selected another parent object.
    subobject_id = (request.subobject_id if "subobject_id" in request.model_fields_set
                    else report.get("subobject_id") if request.object_id in (None, report.get("object_id")) else None)
    if entity_id is not None and request.subobject_id is None:subobject_id=None
    if identities and (entity_id is not None or object_id is not None or subobject_id is not None):
        try:
            entity=identity.resolve(cursor.connection,entity_id=entity_id,object_id=object_id,subobject_id=subobject_id)
            entity_id=entity['entity_id']
            if not entity['is_active']:problems.append('Подобъект неактивен')
        except ValueError as error:problems.append(str(error))
    if subobject_id is not None and not identities:
        cursor.execute("SELECT object_id, is_active FROM construction_subobjects WHERE id = %s FOR SHARE", (subobject_id,))
        child = cursor.fetchone()
        if child is None or not child[1]:
            problems.append("Подобъект не найден или неактивен")
        elif child[0] != object_id:
            problems.append("Подобъект не принадлежит выбранному объекту")
        elif "subobject_id" in request.model_fields_set:
            logging.getLogger(__name__).info("SUBOBJECT_SELECTED: subobject_id=%s object_id=%s", subobject_id, object_id)
    po_ids = [None] if po_absent else [resolved("general_contractor_id", "general_contractor_status", "Генподрядчик")]
    if po_absent and request.general_contractor_id is not None:
        problems.append('При согласованном отсутствии ПО значение должно быть пустым')
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
    elif fields.get('subcontractor',{}).get('absent') and not fields['subcontractor']['approved']:
        problems.append('Субподрядчик: согласуйте отсутствие')

    facts = []
    unique_po_ids = {po_id for po_id in po_ids if po_id}
    if set(request.assignments) - unique_po_ids:
        problems.append("Выбрано назначение для ПО, отсутствующего в отчёте")
    for po_id in ([None] if po_absent else sorted(unique_po_ids)):
        if not employee_id or not (object_id or entity):
            continue
        matches = find_assignment(cursor, employee_id, object_id, po_id, request.absence_assignment_id if po_id is None else request.assignments.get(po_id),entity_id=entity_id if entity else None)
        if len(matches) != 1 or not matches[0].get('category_id'):
            problems.append('Нет категории: выберите категорию действующего назначения')
        else:
            fact = {**matches[0], "subobject_id": subobject_id, "subcontractor_id": subcontractor_id}
            if entity:fact.update(entity_id=entity_id,object_id=object_id)
            facts.append(fact)
    from app.repositories.object_archive import archive_state
    archive_warnings=[]
    for fact in (facts if not problems else []):
        if (identity.reference(cursor.connection,fact)['effectively_archived'] if identities else archive_state(cursor,fact['object_id'],fact.get('subobject_id'))):
            archive_warnings=['Объект или подобъект находится в архиве. Достоверный ежедневный отчёт разрешено сохранить.']
            break
    return {
        "can_save": not problems and bool(facts), "saved": False,
        "warnings": archive_warnings,
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
            identities=identity.enabled(conn)
            if identities:
                identity.require_enabled(conn)
                conn.execute('SELECT pg_advisory_xact_lock(20261013,24)')
            if save:
                # Serialize saves of this source; the unique fact constraint also protects
                # against a renamed/repacked copy submitted concurrently.
                cursor.execute("SELECT pg_advisory_xact_lock(%s)",
                               (int.from_bytes(bytes.fromhex(digest)[:8], signed=True),))
            from app.services import matrix_report_service as matrix_reports
            matrix_reports.ensure_current_source(conn,digest)
            previous = saved_source(cursor, digest)
            if previous:
                if request.replace_fact_id:raise DirectoryConflict('Загруженный файл уже подтверждён. Замена не выполнена.')
                if request.expected_employee_id and any(r['employee_id']!=request.expected_employee_id or str(r['report_date'])!=str(request.expected_report_date) for r in previous):
                    raise ValueError('Сохранённый отчёт не соответствует выбранному сотруднику или дате')
                from app.repositories.object_archive import archive_state
                archived=any(identity.reference(conn,row)['effectively_archived'] if identities else archive_state(cursor,row['object_id'],row.get('subobject_id')) for row in previous)
                return {"can_save": False, "saved": True, "created": False,
                        "warnings": ['Объект или подобъект находится в архиве. Сохранённый факт доступен.'] if archived else [],
                        "report_date": previous[0]["report_date"], "source_file": path.name,
                        "problems": [], "results": [{**row, "created": False} for row in previous]}

            # Both hash and parser use exactly the same immutable bytes.
            source = BytesIO(content)
            source.name = path.name
            document = read_document(source)
            report = prepare_report(document)
            from app.repositories import report_review
            absence=report_review.options(conn,digest,document)
            result = validate_review(cursor, document, report, request,absence)
            # A report-scoped choice overrides its assignment snapshot only for
            # this source. Confirmed sources return above and are never rewritten.
            if absence['enabled']:
                for fact in result.get('facts',[]):
                    selected=report_review.selected_category(conn,digest,fact['employee_id'],fact.get('entity_id'),fact.get('po_id'))
                    if selected:
                        category=conn.execute('SELECT name FROM object_categories WHERE id=%s',(selected['category_id'],)).fetchone()
                        if category:
                            fact.update(category_id=selected['category_id'],category_name=category[0])
            if request.expected_employee_id:
                if str(result['report_date'])!=str(request.expected_report_date) or any(f['employee_id']!=request.expected_employee_id for f in result['facts']):
                    raise ValueError('Отчёт не соответствует выбранному сотруднику или дате')
            preview=matrix_reports.replacement_preview(conn,request,result,digest) if request.replace_fact_id else None
            if preview:result['replacement']=preview
            if save and result["can_save"]:
                if preview and not request.confirm_replacement:raise ValueError('Требуется явное подтверждение замены отчёта')
                if preview and request.replacement_token!=preview['token']:raise DirectoryConflict('Данные изменились после сравнения. Повторите проверку перед заменой.')
                result["results"] = matrix_reports.archive_and_replace(conn,preview,request,result,digest,path.name,insert_fact) if preview else [
                    insert_fact(cursor, result["report_date"], fact, path.name, digest)
                    for fact in result["facts"]
                ]
                result.update(saved=True, can_save=False,
                              created=any(item["created"] for item in result["results"]))
                if absence['enabled']:
                    for field,state in absence['fields'].items():
                        if state['approved']:
                            report_review.event(conn,digest,field,'absence_saved',rule=state['rule'],manual=state['manual'])
            return result
