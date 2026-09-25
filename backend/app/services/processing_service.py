from pathlib import Path

from app.parsers.word_parser import read_document
from app.services.po_matcher import match_po


def list_report_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir()
                  if path.is_file() and path.suffix.lower() == ".docx"
                  and not path.name.startswith("~$"))


def get_field_value(field: dict | None, raw: bool = False) -> str | None:
    if not field or not field.get("found"):
        return None
    return field.get("raw" if raw else "value")


def get_report_status(data: dict, general_po_match: dict, subcontractor_po_match: dict) -> str:
    if any(not data[key]["found"] for key in ("report_date", "object", "inspector", "general_contractor")):
        return "error"
    statuses = [data["employee_match"]["status"], data["object_match"]["status"], general_po_match["status"]]
    if data["subcontractor"]["found"]:
        statuses.append(subcontractor_po_match["status"])
    return "warning" if any(s in {"similar", "new"} for s in statuses) else "ok"


def prepare_report(document: dict) -> dict:
    data = document["business_data"]
    inspector = data["inspector"]
    employee_match = data["employee_match"]
    object_match = data["object_match"]
    general_contractor_value = get_field_value(data["general_contractor"], raw=True)
    subcontractor_value = get_field_value(data["subcontractor"], raw=True)
    general_po_match = match_po(general_contractor_value) if general_contractor_value else {"status": "not_checked", "po": None, "candidates": []}
    subcontractor_po_match = match_po(subcontractor_value) if subcontractor_value else {"status": "not_checked", "po": None, "candidates": []}

    employee_status = employee_match["status"]
    object_status = object_match["status"]
    general_contractor_status = general_po_match["status"]
    subcontractor_status = subcontractor_po_match["status"]

    problems = []
    if not data["report_date"]["found"]:
        problems.append("Дата не распознана")
    if not data["object"]["found"]:
        problems.append("Объект не распознан")
    elif object_status in {"similar", "new"}:
        problems.append(
            "Требуется согласование объекта"
            if object_status == "similar"
            else "Новый объект"
        )
    if not inspector["found"]:
        problems.append("ФИО не распознано")
    elif employee_status in {"similar", "new"}:
        problems.append(
            "Требуется согласование сотрудника"
            if employee_status == "similar"
            else "Новый сотрудник"
        )
    if not data["general_contractor"]["found"]:
        problems.append("Генподрядчик не распознан")
    elif general_contractor_status in {"similar", "new"}:
        problems.append("Требуется согласование генподрядчика" if general_contractor_status == "similar" else "Новый генподрядчик")
    if data["subcontractor"]["found"] and subcontractor_status in {"similar", "new"}:
        problems.append("Требуется согласование субподрядчика" if subcontractor_status == "similar" else "Новый субподрядчик")

    employee = (
        employee_match.get("employee")
        if employee_match["status"] == "found"
        else None
    )
    database_object = object_match.get("object") if object_status == "found" else None
    general_po = general_po_match.get("po") if general_contractor_status == "found" else None
    subcontractor_po = subcontractor_po_match.get("po") if subcontractor_status == "found" else None

    return {
        "filename": document["filename"],
        "full_name": inspector["full_name"]["value"] if inspector["found"] else None,
        "employee_id": employee.get("id") if employee else None,
        "position": employee.get("position_name") if employee else None,
        "report_date": get_field_value(data["report_date"], raw=True),
        "object_name": get_field_value(data["object"], raw=True),
        "object_id": database_object.get("id") if database_object else None,
        "general_contractor": general_contractor_value,
        "subcontractor": subcontractor_value,
        "general_contractor_id": general_po.get("id") if general_po else None,
        "subcontractor_id": subcontractor_po.get("id") if subcontractor_po else None,
        "employee_status": employee_status,
        "object_status": object_status,
        "general_contractor_status": general_contractor_status,
        "subcontractor_status": subcontractor_status,
        "status": get_report_status(data, general_po_match, subcontractor_po_match),
        "problems": problems,
        "employee_candidates": employee_match.get("candidates", []),
        "object_candidates": object_match.get("candidates", []),
        "general_contractor_candidates": general_po_match.get("candidates", []),
        "subcontractor_candidates": subcontractor_po_match.get("candidates", []),
    }


build_report_result = prepare_report


def process_folder(folder_path: str | Path) -> dict:
    """Обрабатывает DOCX-папку и возвращает JSON-совместимый результат для UI."""
    folder = Path(folder_path)

    if not folder.exists():
        raise ValueError("Указанная папка не существует")
    if not folder.is_dir():
        raise ValueError("Указанный путь не является папкой")

    reports = []
    errors = []

    files = list_report_files(folder)
    for file_path in files:
        try:
            reports.append(prepare_report(read_document(file_path)))
        except Exception as error:
            errors.append({
                "filename": file_path.name,
                "error": str(error),
            })

    reports.sort(key=lambda report: (report["full_name"] or "").lower())
    return {
        "total": len(files),
        "ok": sum(report["status"] == "ok" for report in reports),
        "warning": sum(report["status"] == "warning" for report in reports),
        "error": len(errors) + sum(report["status"] == "error" for report in reports),
        "reports": reports,
        "processing_errors": errors,
    }
