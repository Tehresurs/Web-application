import logging
from app.repositories.value_aliases import resolve_value_alias

from difflib import SequenceMatcher
from app.database.db import get_connection

SIMILARITY_THRESHOLD = 0.75

def normalize_po_name(name: str) -> str:
    if not name:
        return ""
    return " ".join(name.strip().lower().replace("ё", "е").replace("«", '"').replace("»", '"').split())

def calculate_similarity(name_1: str, name_2: str) -> float:
    a, b = normalize_po_name(name_1), normalize_po_name(name_2)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0

def get_all_po_types():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name FROM po_types ORDER BY name;")
            rows = cursor.fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]

def subcontractor_is_absent(name):
    return name is None or str(name).strip() in {"", "-", "–", "—", "−", "‑", "‒"}


def match_po(name: str):
    return _match_organization(name, "po")


def match_subcontractor(name):
    if subcontractor_is_absent(name):
        return {"status": "not_applicable", "po": None, "candidates": [], "entity_type": "subcontractor"}
    return {**_match_organization(name, "subcontractor"), "entity_type": "subcontractor"}


def _match_organization(name, entity_type):
    items = get_all_po_types()
    normalized = normalize_po_name(name)
    for item in items:
        if normalized == normalize_po_name(item["name"]):
            if entity_type == "subcontractor":
                logging.getLogger(__name__).info("SUBCONTRACTOR_EXACT_MATCH: %r target_id=%s", name, item["id"])
            return {"status": "found", "po": item, "candidates": []}
    alias = resolve_value_alias(entity_type, name) if name else None
    if alias:
        target = next((item for item in items if item["id"] == alias["target_id"]), None)
        if target:
            event = "SUBCONTRACTOR_ALIAS_MATCH" if entity_type == "subcontractor" else "ALIAS_MATCH po"
            logging.getLogger(__name__).info("%s: %r -> %r target_id=%s", event, name, alias["target_name"], target["id"])
            return {"status": "found", "po": target, "candidates": [], "match_source": "alias", "alias_id": alias["id"]}

    candidates = []
    for item in items:
        score = calculate_similarity(name, item["name"])
        if score >= SIMILARITY_THRESHOLD:
            candidates.append({"po": item, "similarity": score})
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    if candidates:
        return {"status": "similar", "po": None, "candidates": candidates[:5]}
    return {"status": "new", "po": None, "candidates": []}
