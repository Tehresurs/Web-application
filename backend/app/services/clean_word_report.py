"""Parse one Word report and resolve its references only in a clean-start DB."""
from difflib import SequenceMatcher
from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from psycopg.rows import dict_row

from app.parsers.word_parser import (
    clean_text,
    find_general_contractor,
    find_inspector,
    find_object,
    find_report_date,
    find_subcontractor,
    get_table_rows,
)
from app.services.clean_construction_matcher import match_word_object

EMPLOYEE_SIMILARITY_THRESHOLD = 0.78
ORGANIZATION_SIMILARITY_THRESHOLD = 0.75


class InvalidWordDocument(ValueError):
    """The uploaded bytes are not a readable DOCX document."""


def _normalize_name(value):
    return ' '.join(value.strip().lower().replace('ё', 'е').split())


def _similarity(left, right):
    normalized_left = _normalize_name(left)
    normalized_right = _normalize_name(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _employee_match(conn, inspector):
    if not inspector['found']:
        return {
            'status': 'unknown',
            'reason': inspector['status'],
            'employee_id': None,
            'employee': None,
            'candidates': [],
        }

    raw_name = inspector['full_name']['raw']
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            '''SELECT e.id,e.full_name,e.position_id,p.name AS position_name,
                      e.is_archived
               FROM public.employees e
               LEFT JOIN public.positions p ON p.id=e.position_id
               ORDER BY e.full_name,e.id'''
        )
        employees = cursor.fetchall()

    normalized = _normalize_name(raw_name)
    exact = [
        employee for employee in employees
        if _normalize_name(employee['full_name']) == normalized
    ]
    if len(exact) > 1:
        return {
            'status': 'ambiguous',
            'reason': 'multiple_exact_matches',
            'employee_id': None,
            'employee': None,
            'candidates': exact,
        }
    if exact:
        employee = exact[0]
        if employee['is_archived']:
            return {
                'status': 'unknown',
                'reason': 'employee_archived',
                'employee_id': None,
                'employee': None,
                'candidates': [employee],
            }
        return {
            'status': 'exact',
            'reason': None,
            'employee_id': employee['id'],
            'employee': employee,
            'candidates': [],
        }

    candidates = []
    for employee in employees:
        if employee['is_archived']:
            continue
        score = _similarity(raw_name, employee['full_name'])
        if score >= EMPLOYEE_SIMILARITY_THRESHOLD:
            candidates.append({**employee, 'similarity': score})
    candidates.sort(key=lambda candidate: (-candidate['similarity'], candidate['id']))
    if candidates:
        return {
            'status': 'similar',
            'reason': 'review_required',
            'employee_id': None,
            'employee': None,
            'candidates': candidates[:5],
        }
    return {
        'status': 'unknown',
        'reason': 'no_employee_match',
        'employee_id': None,
        'employee': None,
        'candidates': [],
    }


def _organization_match(conn, raw_name, *, optional=False):
    if optional and (raw_name is None or raw_name.strip() in {'', '-', '–', '—', '−', '‑', '‒'}):
        return {
            'status': 'not_applicable',
            'reason': None,
            'po_id': None,
            'organization': None,
            'candidates': [],
        }
    if not raw_name:
        return {
            'status': 'unknown',
            'reason': 'name_not_found',
            'po_id': None,
            'organization': None,
            'candidates': [],
        }

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            'SELECT id,name FROM public.po_types ORDER BY name,id'
        )
        organizations = cursor.fetchall()

    normalized = _normalize_name(raw_name).replace('«', '"').replace('»', '"')
    exact = [
        item for item in organizations
        if _normalize_name(item['name']).replace('«', '"').replace('»', '"') == normalized
    ]
    if len(exact) > 1:
        return {
            'status': 'ambiguous',
            'reason': 'multiple_exact_matches',
            'po_id': None,
            'organization': None,
            'candidates': exact,
        }
    if exact:
        return {
            'status': 'exact',
            'reason': None,
            'po_id': exact[0]['id'],
            'organization': exact[0],
            'candidates': [],
        }

    candidates = []
    for organization in organizations:
        score = _similarity(raw_name, organization['name'])
        if score >= ORGANIZATION_SIMILARITY_THRESHOLD:
            candidates.append({**organization, 'similarity': score})
    candidates.sort(key=lambda candidate: (-candidate['similarity'], candidate['id']))
    if candidates:
        return {
            'status': 'similar',
            'reason': 'review_required',
            'po_id': None,
            'organization': None,
            'candidates': candidates[:5],
        }
    return {
        'status': 'unknown',
        'reason': 'no_organization_match',
        'po_id': None,
        'organization': None,
        'candidates': [],
    }


def _issue(code, message, field, *, requires_approval=False):
    return {
        'code': code,
        'message': message,
        'field': field,
        'requires_approval': requires_approval,
    }


def _build_report(filename, business_data):
    date_field = business_data['report_date']
    object_field = business_data['object']
    inspector = business_data['inspector']
    employee_match = business_data['employee_match']
    object_match = business_data['object_match']
    general_match = business_data['general_contractor_match']
    subcontractor_match = business_data['subcontractor_match']
    errors = []

    if not date_field['found']:
        errors.append(_issue('report_date_not_found', 'Дата отчёта не распознана', 'report_date'))
    if not object_field['found']:
        errors.append(_issue('object_name_not_found', 'Название объекта не распознано', 'object'))
    if not inspector['found']:
        errors.append(_issue(
            'inspector_name_invalid' if inspector['status'] == 'invalid_name' else 'inspector_name_not_found',
            'ФИО инженера не распознано' if inspector['status'] != 'invalid_name'
            else 'В предпоследней строке первой таблицы не указано полное ФИО',
            'inspector',
        ))
    if employee_match['status'] in {'similar', 'unknown', 'ambiguous'}:
        errors.append(_issue(
            'employee_match_' + employee_match['status'],
            'Сотрудник требует проверки; автоматическая подмена ФИО не выполнялась',
            'employee',
            requires_approval=True,
        ))
    if object_match['status'] != 'exact' and object_match['status'] != 'alias':
        errors.append(_issue(
            'object_match_' + object_match['status'],
            'Объект требует согласования; автоматический выбор не выполнялся',
            'object',
            requires_approval=True,
        ))
    if not business_data['general_contractor']['found']:
        errors.append(_issue(
            'general_contractor_not_found',
            'Генподрядчик не распознан',
            'general_contractor',
        ))
    elif general_match['status'] != 'exact':
        errors.append(_issue(
            'general_contractor_match_' + general_match['status'],
            'Генподрядчик требует проверки; автоматическая подмена не выполнялась',
            'general_contractor',
            requires_approval=True,
        ))
    if subcontractor_match['status'] not in {'exact', 'not_applicable'}:
        errors.append(_issue(
            'subcontractor_match_' + subcontractor_match['status'],
            'Субподрядчик требует проверки; автоматическая подмена не выполнялась',
            'subcontractor',
            requires_approval=True,
        ))

    if any(not issue['requires_approval'] for issue in errors):
        status = 'error'
    elif errors:
        status = 'needs_review'
    else:
        status = 'ready'

    return {
        'filename': filename,
        'status': status,
        'full_name': inspector['full_name']['raw'] if inspector['full_name'] else None,
        'employee_id': employee_match['employee_id'],
        'report_date': date_field['value'],
        'report_date_raw': date_field['raw'],
        'object_name': object_field['raw'] or object_field['value'],
        'entity_id': object_match.get('entity_id'),
        'current_hierarchy': object_match.get('entity', {}).get('current_hierarchy'),
        'general_contractor': business_data['general_contractor']['raw'],
        'general_contractor_id': general_match['po_id'],
        'subcontractor': business_data['subcontractor']['raw'],
        'subcontractor_id': subcontractor_match['po_id'],
        'business_data': business_data,
        'errors': errors,
    }


def parse_clean_word_report(conn, content, filename):
    """Parse a DOCX in memory and resolve every reference on the supplied connection."""
    try:
        document = Document(BytesIO(content))
        paragraphs = [
            {'index': index, 'text': text}
            for index, paragraph in enumerate(document.paragraphs)
            if (text := clean_text(paragraph.text))
        ]
        tables = [
            {'table_index': index, 'rows': get_table_rows(table)}
            for index, table in enumerate(document.tables)
        ]
    except (BadZipFile, PackageNotFoundError, KeyError, ValueError) as error:
        raise InvalidWordDocument('Unable to read DOCX content') from error

    inspector = find_inspector(tables)
    object_field = find_object(tables)
    raw_object_name = (object_field['raw'] or object_field['value']) if object_field['found'] else None
    object_match = (
        match_word_object(conn, raw_object_name)
        if raw_object_name
        else {
            'raw_name': None,
            'normalized_name': None,
            'entity_id': None,
            'status': 'needs_review',
            'reason': 'unknown',
            'candidates': [],
        }
    )
    object_status = (
        object_match['match_source']
        if object_match['status'] == 'found'
        else object_match['reason']
    )
    if object_status == 'unavailable_exact_match':
        object_status = 'unknown'
    object_match = {
        **object_match,
        'status': object_status,
        'requires_approval': object_status not in {'exact', 'alias'},
    }
    raw_general_contractor = find_general_contractor(tables)
    raw_subcontractor = find_subcontractor(tables)
    general_raw = raw_general_contractor['raw'] if raw_general_contractor['found'] else None
    subcontractor_raw = raw_subcontractor['raw'] if raw_subcontractor['found'] else None
    employee_match = _employee_match(conn, inspector)
    general_match = _organization_match(conn, general_raw)
    subcontractor_match = _organization_match(
        conn, subcontractor_raw, optional=True
    )
    business_data = {
        'report_date': find_report_date(tables),
        'object': object_field,
        'object_match': object_match,
        'inspector': inspector,
        'employee_match': employee_match,
        'general_contractor': raw_general_contractor,
        'general_contractor_match': general_match,
        'subcontractor': raw_subcontractor,
        'subcontractor_match': subcontractor_match,
    }
    report = _build_report(filename, business_data)
    report['document'] = {'paragraphs': paragraphs}
    return report
