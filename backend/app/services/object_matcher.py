from difflib import SequenceMatcher

from app.database.db import get_connection

SIMILARITY_THRESHOLD = 0.75


def normalize_object_name(name: str) -> str:
    """Нормализация используется только для сравнения."""
    if not name:
        return ""

    return " ".join(
        name.strip().lower().replace("ё", "е").replace("№ ", "№").split()
    )


def calculate_similarity(name_1: str, name_2: str) -> float:
    value_1 = normalize_object_name(name_1)
    value_2 = normalize_object_name(name_2)

    if not value_1 or not value_2:
        return 0.0

    return SequenceMatcher(None, value_1, value_2).ratio()


def get_all_objects():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    o.id,
                    o.name,
                    o.category_id,
                    c.name AS category_name
                FROM construction_objects o
                LEFT JOIN object_categories c
                    ON c.id = o.category_id
                ORDER BY o.name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "category_id": row[2],
            "category_name": row[3],
        }
        for row in rows
    ]


def match_object(object_name: str):
    objects = get_all_objects()
    normalized_word_name = normalize_object_name(object_name)

    for obj in objects:
        if normalize_object_name(obj["name"]) == normalized_word_name:
            return {
                "status": "found",
                "object": obj,
                "candidates": [],
            }

    candidates = []
    for obj in objects:
        similarity = calculate_similarity(object_name, obj["name"])
        if similarity >= SIMILARITY_THRESHOLD:
            candidates.append({"object": obj, "similarity": similarity})

    candidates.sort(key=lambda item: item["similarity"], reverse=True)

    if candidates:
        return {
            "status": "similar",
            "object": None,
            "candidates": candidates[:5],
        }

    return {
        "status": "new",
        "object": None,
        "candidates": [],
        "new_object": {
            "name": object_name,
            "category_id": None,
            "po_ids": [],
        },
    }
