from html import escape
from pathlib import Path

OUTPUT_FILE = Path("output/intermediate_report.html")


def normalize_sort_name(value: str) -> str:
    if not value:
        return "яяяяяя"
    return " ".join(value.split()).lower().replace("ё", "е")


def get_inspector_name(document):
    inspector = document["business_data"]["inspector"]
    return inspector["full_name"]["value"] if inspector["found"] else ""


def get_field_value(field):
    if not field or not field.get("found"):
        return ""
    return field.get("raw") or field.get("value") or ""


def get_employee_position(document):
    match = document["business_data"]["employee_match"]
    if match["status"] != "found":
        return ""
    return match["employee"].get("position_name") or ""


def get_status(document):
    data = document["business_data"]
    problems = []

    if not data["report_date"]["found"]:
        problems.append("Дата не распознана")
    if not data["object"]["found"]:
        problems.append("Объект не распознан")
    else:
        object_match = data["object_match"]
        if object_match["status"] == "similar":
            problems.append("Требуется согласование объекта")
        elif object_match["status"] == "new":
            problems.append("Новый объект")
    if not data["inspector"]["found"]:
        problems.append("ФИО не распознано")
        return "error", "; ".join(problems)

    match = data["employee_match"]
    if match["status"] == "similar":
        problems.append("Требуется согласование сотрудника")
    elif match["status"] == "new":
        problems.append("Новый сотрудник")

    if not data["general_contractor"]["found"]:
        problems.append("Генподрядчик не распознан")

    return ("warning", "; ".join(problems)) if problems else ("ok", "OK")


def build_employee_match_details(document):
    data = document["business_data"]
    inspector = data["inspector"]
    match = data["employee_match"]

    if not inspector["found"] or match["status"] == "found":
        return ""

    full_name = inspector["full_name"]["value"]
    if match["status"] == "new":
        return (
            '<div class="match-warning"><strong>Новый сотрудник</strong><br>'
            f'ФИО из Word: {escape(full_name)}<br>'
            'Совпадений в базе не найдено.</div>'
        )

    if match["status"] == "similar":
        html = (
            '<div class="match-warning"><strong>Требуется согласование</strong><br>'
            f'ФИО из Word: {escape(full_name)}<br><br>'
            'Возможные совпадения:<table>'
            '<tr><th>ФИО в базе</th><th>Должность</th><th>Похожесть</th></tr>'
        )
        for candidate in match["candidates"]:
            employee = candidate["employee"]
            position = employee["position_name"] or "—"
            similarity = round(candidate["similarity"] * 100, 1)
            html += (
                "<tr>"
                f'<td>{escape(employee["full_name"])}</td>'
                f"<td>{escape(position)}</td>"
                f"<td>{similarity} %</td></tr>"
            )
        return html + "</table></div>"

    return ""


def build_object_match_details(document):
    data = document["business_data"]
    object_data = data["object"]
    match = data["object_match"]

    if not object_data["found"]:
        return ""

    object_name = object_data["raw"] or object_data["value"]

    if match["status"] == "new":
        return (
            '<div class="match-warning"><strong>Новый объект</strong><br><br>'
            f'<strong>Из Word:</strong><br>{escape(object_name)}<br><br>'
            'Объект отсутствует в постоянной базе.</div>'
        )

    if match["status"] == "similar":
        html = (
            '<div class="match-warning"><strong>Требуется согласование объекта</strong>'
            f'<br><br><strong>Из Word:</strong><br>{escape(object_name)}<br><br>'
            'Возможные совпадения:<table>'
            '<tr><th>Объект в базе</th><th>Категория</th><th>Похожесть</th></tr>'
        )
        for candidate in match["candidates"]:
            obj = candidate["object"]
            category = obj["category_name"] or "—"
            similarity = round(candidate["similarity"] * 100, 1)
            html += (
                "<tr>"
                f'<td>{escape(obj["name"])}</td>'
                f"<td>{escape(category)}</td>"
                f"<td>{similarity} %</td></tr>"
            )
        return html + "</table></div>"

    return ""


def collect_new_objects(documents):
    new_objects = {}

    for document in documents:
        data = document["business_data"]
        match = data.get("object_match")

        if not match or match["status"] != "new":
            continue

        object_data = data["object"]
        if not object_data["found"]:
            continue

        object_name = object_data["raw"] or object_data["value"]
        key = " ".join(
            object_name.lower().replace("ё", "е").replace("№ ", "№").split()
        )

        if key not in new_objects:
            new_objects[key] = {"name": object_name, "documents": []}

        new_objects[key]["documents"].append(document["filename"])

    return list(new_objects.values())


def build_new_objects_summary(documents):
    objects = collect_new_objects(documents)

    if not objects:
        return "<h2>Новые объекты</h2><p>✓ Новых объектов нет.</p>"

    html = """
<h2>Новые объекты</h2>
<p>Эти объекты отсутствуют в постоянной базе. Они ещё НЕ добавлены.</p>
<table>
<tr><th>№</th><th>Наименование из Word</th><th>Отчётов</th><th>Категория</th><th>ПО</th><th>Статус</th></tr>
"""

    for number, obj in enumerate(objects, start=1):
        html += (
            f'<tr><td>{number}</td><td>{escape(obj["name"])}</td>'
            f'<td>{len(obj["documents"])}</td><td>—</td><td>—</td>'
            '<td class="warning">Ожидает подтверждения</td></tr>'
        )

    return html + "</table>"


def build_intermediate_report(documents):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    sorted_documents = sorted(
        documents,
        key=lambda document: (
            normalize_sort_name(get_inspector_name(document)),
            get_field_value(document["business_data"]["report_date"]),
            get_field_value(document["business_data"]["object"]),
        ),
    )

    html = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<title>Промежуточный отчёт парсинга</title>
<style>
body{font-family:Arial,sans-serif;margin:30px;background:#f5f6f8}
.container{background:#fff;padding:25px;border-radius:10px}
h1{margin-top:0}table{width:100%;border-collapse:collapse}
th,td{border:1px solid #d7d7d7;padding:8px;vertical-align:top}th{background:#eee}
.ok{font-weight:bold}.warning{font-weight:bold}.error{font-weight:bold}
.match-warning{background:#fff7d6;border:1px solid #eadb9c;padding:15px;margin:20px 0}
.filename{font-size:11px;color:#777;margin-top:5px}
</style></head><body><div class="container">
<h1>Промежуточный отчёт парсинга</h1><table>
<tr><th>№</th><th>ФИО</th><th>Должность из БД</th><th>Дата</th><th>Объект</th><th>Генподрядчик</th><th>Субподрядчик</th><th>Статус</th></tr>
"""

    for number, document in enumerate(sorted_documents, start=1):
        data = document["business_data"]
        full_name = get_inspector_name(document) or "—"
        position = get_employee_position(document) or "—"
        report_date = get_field_value(data["report_date"])
        object_name = get_field_value(data["object"])
        general_contractor = get_field_value(data["general_contractor"])
        subcontractor = get_field_value(data["subcontractor"]) or "—"
        status_type, status_text = get_status(document)
        html += (
            f'<tr><td>{number}</td><td><strong>{escape(full_name)}</strong>'
            f'<div class="filename">{escape(document["filename"])}</div></td>'
            f'<td>{escape(position)}</td><td>{escape(report_date)}</td>'
            f'<td>{escape(object_name)}</td><td>{escape(general_contractor)}</td>'
            f'<td>{escape(subcontractor)}</td><td class="{status_type}">'
            f'{escape(status_text)}</td></tr>'
        )

    html += "</table><h2>Требуют внимания</h2>"
    employee_attention = [
        details for details in (
            build_employee_match_details(document)
            for document in sorted_documents
        ) if details
    ]
    html += "".join(employee_attention) or "<p>✓ Несоответствий по сотрудникам нет.</p>"

    html += "<h2>Объекты, требующие внимания</h2>"
    object_attention = [
        details for details in (
            build_object_match_details(document)
            for document in sorted_documents
        ) if details
    ]
    html += "".join(object_attention) or "<p>✓ Несоответствий по объектам нет.</p>"
    html += build_new_objects_summary(sorted_documents)
    html += "</div></body></html>"
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    return OUTPUT_FILE
