from pathlib import Path

from app.parsers.word_parser import read_document


def list_report_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir()
                  if path.is_file() and path.suffix.lower() == ".docx"
                  and not path.name.startswith("~$"))


def get_field_value(field: dict | None, raw: bool = False) -> str | None:
    if not field or not field.get("found"):
        return None
    return field.get("raw" if raw else "value")


def get_report_status(data: dict) -> str:
    """Отсутствие обязательных данных — ошибка, согласование — предупреждение."""
    if any(not data[key]["found"] for key in (
        "report_date", "object", "inspector", "general_contractor",
    )):
        return "error"
    if any(data[key]["status"] in {"similar", "new"}
           for key in ("employee_match", "object_match")):
        return "warning"
    return "ok"


def prepare_report(document: dict) -> dict:
    data = document["business_data"]
    inspector = data["inspector"]
    employee_match = data["employee_match"]
    object_match = data["object_match"]

    employee_status = employee_match["status"]
    object_status = object_match["status"]

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

    employee = (
        employee_match.get("employee")
        if employee_match["status"] == "found"
        else None
    )
    database_object = object_match.get("object") if object_status == "found" else None

    return {
        "filename": document["filename"],
        "full_name": inspector["full_name"]["value"] if inspector["found"] else None,
        "employee_id": employee.get("id") if employee else None,
        "position": employee.get("position_name") if employee else None,
        "report_date": get_field_value(data["report_date"], raw=True),
        "object_name": get_field_value(data["object"], raw=True),
        "object_id": database_object.get("id") if database_object else None,
        "general_contractor": get_field_value(data["general_contractor"], raw=True),
        "subcontractor": get_field_value(data["subcontractor"], raw=True),
        "employee_status": employee_status,
        "object_status": object_status,
        "status": get_report_status(data),
        "problems": problems,
        "employee_candidates": employee_match.get("candidates", []),
        "object_candidates": object_match.get("candidates", []),
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
