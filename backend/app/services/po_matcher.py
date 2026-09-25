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

def match_po(name: str):
    items = get_all_po_types()
    normalized = normalize_po_name(name)
    for item in items:
        if normalized == normalize_po_name(item["name"]):
            return {"status": "found", "po": item, "candidates": []}
    candidates = []
    for item in items:
        score = calculate_similarity(name, item["name"])
        if score >= SIMILARITY_THRESHOLD:
            candidates.append({"po": item, "similarity": score})
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    if candidates:
        return {"status": "similar", "po": None, "candidates": candidates[:5]}
    return {"status": "new", "po": None, "candidates": []}
