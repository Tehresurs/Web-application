"""Read-only Word-name matching against the isolated clean-start catalog."""
from difflib import SequenceMatcher

from psycopg.rows import dict_row

SIMILARITY_THRESHOLD = 0.75


def _normalize_for_similarity(value):
    return ' '.join(value.strip().lower().replace('ё', 'е').replace('№ ', '№').split())


def _candidate(row, similarity=None):
    parent = None
    if row['parent_entity_id'] is not None:
        parent = {
            'entity_id': row['parent_entity_id'],
            'name': row['parent_name'],
            'is_active': row['parent_is_active'],
            'is_archived': row['parent_is_archived'],
        }
    effectively_archived = row['is_archived'] or bool(
        parent and parent['is_archived']
    )
    available = row['is_active'] and not effectively_archived and (
        parent is None or parent['is_active']
    )
    item = {
        'entity_id': row['entity_id'],
        'name': row['name'],
        'kind': 'subobject' if parent else 'object',
        'parent_entity_id': row['parent_entity_id'],
        'parent_name': row['parent_name'],
        'activity_status': row['activity_status'],
        'is_active': row['is_active'],
        'is_archived': row['is_archived'],
        'effectively_archived': effectively_archived,
        'available': available,
        'current_hierarchy': {
            'entity_id': row['entity_id'],
            'name': row['name'],
            'parent_entity_id': row['parent_entity_id'],
            'parent': parent,
        },
    }
    if similarity is not None:
        item['similarity'] = similarity
    return item, available


def match_word_object(conn, raw_name):
    """Return a stable entity match or an explicit review result, never a guess."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            '''WITH input AS (
                   SELECT public.normalize_known_value('object', %s) AS normalized_name
               )
               SELECT e.entity_id,e.name,e.parent_entity_id,e.activity_status,
                      e.is_active,e.is_archived,
                      p.name AS parent_name,p.is_active AS parent_is_active,
                      p.is_archived AS parent_is_archived,
                      input.normalized_name,
                      public.normalize_known_value('object',e.name)=input.normalized_name
                          AS exact_name_match,
                      EXISTS (
                          SELECT 1
                          FROM public.construction_entity_aliases a
                          WHERE a.entity_id=e.entity_id
                            AND a.normalized_source_value=input.normalized_name
                      ) AS alias_match
               FROM input
               LEFT JOIN public.construction_entities e ON TRUE
               LEFT JOIN public.construction_entities p ON p.entity_id=e.parent_entity_id
               ORDER BY e.entity_id''',
            (raw_name,),
        )
        rows = cursor.fetchall()

    normalized_name = rows[0]['normalized_name'] if rows else None
    exact_rows = [
        row for row in rows
        if row['entity_id'] is not None and (row['exact_name_match'] or row['alias_match'])
    ]
    base = {
        'raw_name': raw_name,
        'normalized_name': normalized_name,
        'entity_id': None,
    }

    if len(exact_rows) > 1:
        candidates = [_candidate(row)[0] for row in exact_rows]
        return {
            **base,
            'status': 'needs_review',
            'reason': 'ambiguous',
            'candidates': candidates,
        }

    if exact_rows:
        row = exact_rows[0]
        candidate, available = _candidate(row)
        if not available:
            return {
                **base,
                'status': 'needs_review',
                'reason': 'unavailable_exact_match',
                'candidates': [candidate],
            }
        match_source = (
            'exact' if row['exact_name_match']
            else 'alias'
        )
        return {
            **base,
            'status': 'found',
            'entity_id': row['entity_id'],
            'match_source': match_source,
            'entity': candidate,
            'candidates': [],
        }

    normalized_input = _normalize_for_similarity(raw_name)
    similar = []
    for row in rows:
        if row['entity_id'] is None:
            continue
        normalized_candidate = _normalize_for_similarity(row['name'])
        score = SequenceMatcher(None, normalized_input, normalized_candidate).ratio()
        if score >= SIMILARITY_THRESHOLD:
            item, _ = _candidate(row, score)
            similar.append(item)
    similar.sort(key=lambda item: (-item['similarity'], item['entity_id']))
    if similar:
        return {
            **base,
            'status': 'needs_review',
            'reason': 'similar',
            'candidates': similar[:5],
        }

    return {
        **base,
        'status': 'needs_review',
        'reason': 'unknown',
        'candidates': [],
    }
