from difflib import SequenceMatcher

from app.database.db import get_connection

SIMILARITY_THRESHOLD = 0.78


def normalize_full_name(full_name: str) -> str:
    """Нормализация используется только для сравнения."""
    if not full_name:
        return ""

    return " ".join(
        full_name.strip().lower().replace("ё", "е").split()
    )


def calculate_similarity(name_1: str, name_2: str) -> float:
    """Возвращает степень похожести от 0 до 1."""
    normalized_1 = normalize_full_name(name_1)
    normalized_2 = normalize_full_name(name_2)

    if not normalized_1 or not normalized_2:
        return 0.0

    return SequenceMatcher(None, normalized_1, normalized_2).ratio()


def get_all_employees():
    """Получает сотрудников вместе с должностью из БД."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    e.id,
                    e.full_name,
                    e.phone,
                    e.position_id,
                    p.name AS position_name,
                    e.crew_id,
                    c.name AS crew_name
                FROM employees e
                LEFT JOIN positions p ON p.id = e.position_id
                LEFT JOIN crews c ON c.id = e.crew_id
                ORDER BY e.full_name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "full_name": row[1],
            "phone": row[2],
            "position_id": row[3],
            "position_name": row[4],
            "crew_id": row[5],
            "crew_name": row[6],
        }
        for row in rows
    ]


def match_employee(full_name: str):
    """Сопоставляет ФИО из Word с постоянной БД."""
    employees = get_all_employees()
    normalized_word_name = normalize_full_name(full_name)

    for employee in employees:
        if normalized_word_name == normalize_full_name(employee["full_name"]):
            return {
                "status": "found",
                "employee": employee,
                "candidates": [],
            }

    candidates = [
        {
            "employee": employee,
            "similarity": calculate_similarity(full_name, employee["full_name"]),
        }
        for employee in employees
        if calculate_similarity(full_name, employee["full_name"]) >= SIMILARITY_THRESHOLD
    ]
    candidates.sort(key=lambda item: item["similarity"], reverse=True)

    if candidates:
        return {
            "status": "similar",
            "employee": None,
            "candidates": candidates[:5],
        }

    return {
        "status": "new",
        "employee": None,
        "candidates": [],
    }


def find_employee_by_full_name(full_name: str):
    """Совместимость со старым API парсера."""
    return match_employee(full_name)
