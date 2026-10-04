import logging
from app.repositories.value_aliases import resolve_value_alias
from app.repositories.subobjects import get_subobjects

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
                    o.name
                FROM construction_objects o
                ORDER BY o.name;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
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
                "object_id": obj["id"], "object_name": obj["name"], "subobject_id": None,
                "candidates": [],
            }

    alias = resolve_value_alias("object", object_name) if object_name else None
    if alias:
        target = next((item for item in objects if item["id"] == alias["target_id"]), None)
        if target:
            logging.getLogger(__name__).info("ALIAS_MATCH object: %r -> %r target_id=%s", object_name, alias["target_name"], target["id"])
            return {"status": "found", "object": target, "object_id": target["id"],
                    "object_name": target["name"], "subobject_id": None,
                    "candidates": [], "match_source": "alias", "alias_id": alias["id"]}

    subobjects = get_subobjects()
    exact = [item for item in subobjects if normalize_object_name(item["name"]) == normalized_word_name]
    if len(exact) == 1:
        return subobject_result(exact[0], object_name, "subobject_exact")

    alias = resolve_value_alias("subobject", object_name) if object_name else None
    if alias:
        target = next((item for item in subobjects if item["id"] == alias["target_id"]), None)
        if target:
            return subobject_result(target, object_name, "subobject_alias")

    # Identical names under different parents require an explicit selection.
    candidates = []
    for obj in objects:
        similarity = calculate_similarity(object_name, obj["name"])
        if similarity >= SIMILARITY_THRESHOLD:
            candidates.append({"entity_kind": "object", "object": obj, "object_id": obj["id"],
                               "object_name": obj["name"], "subobject_id": None,
                               "similarity": similarity, "score": similarity})

    for item in subobjects:
        score = calculate_similarity(object_name, item["name"])
        if score >= SIMILARITY_THRESHOLD:
            candidates.append({"entity_kind": "subobject", "subobject": item,
                               "subobject_id": item["id"], "subobject_name": item["name"],
                               "object_id": item["object_id"], "object_name": item["object_name"],
                               "similarity": score, "score": score})

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
        },
    }


def subobject_result(item, source, match_source):
    event = "SUBOBJECT_EXACT_MATCH" if match_source == "subobject_exact" else "SUBOBJECT_ALIAS_MATCH"
    logging.getLogger(__name__).info("%s: %r -> subobject_id=%s object_id=%s", event, source, item["id"], item["object_id"])
    return {"status": "found", "match_source": match_source, "candidates": [],
            "object": {"id": item["object_id"], "name": item["object_name"]},
            "subobject": item, "object_id": item["object_id"], "object_name": item["object_name"],
            "subobject_id": item["id"], "subobject_name": item["name"]}
