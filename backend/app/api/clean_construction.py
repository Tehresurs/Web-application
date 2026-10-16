"""Isolated clean-start catalog. No legacy routes, IDs or resolver dependencies.

Explicit configuration: APP_DB_PROFILE=test, CLEAN_START_DB_PROFILE=test,
CLEAN_START_DB_NAME=<approved rehearsal/copy>, CLEAN_START_DB_SCHEMA=public,
CLEAN_START_DB_HOST/PORT/USER/PASSWORD. No fallback to DB_* settings.
"""
import os
import re
from contextlib import contextmanager
from datetime import date
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, File, HTTPException, Path, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictBool

router = APIRouter(prefix='/api/clean-construction-entities', tags=['Clean-start catalog'])
Status = Literal['ACTIVE', 'SUSPENDED', 'COMPLETED']
MAX_WORD_REPORT_BYTES = 10 * 1024 * 1024


class CreateEntity(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=1000)
    activity_status: Status = 'ACTIVE'
    category_id: int | None = Field(default=None, gt=0, strict=True)
    parent_entity_id: int | None = Field(default=None, gt=0, strict=True)


class Version(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(gt=0, strict=True)


class EditEntity(Version):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=1000)
    activity_status: Status | None = None
    category_id: int | None = Field(default=None, gt=0, strict=True)


class Hierarchy(Version):
    parent_entity_id: int | None = Field(..., gt=0, strict=True)
    confirmed: StrictBool


class EmployeeAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(gt=0, strict=True)
    po_id: int = Field(gt=0, strict=True)
    category_id: int = Field(gt=0, strict=True)


class ConstructionAliasInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    entity_id: int = Field(gt=0, strict=True)
    source_value: str = Field(min_length=1, max_length=1000)


class WordObjectMatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    object_name: str = Field(min_length=1, max_length=1000)


class CleanWordReportConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: StrictBool
    report_date: date
    source_full_name: str | None = Field(default=None, max_length=255)
    employee_id: int = Field(gt=0, strict=True)
    source_object_name: str | None = Field(default=None, max_length=1000)
    entity_id: int = Field(gt=0, strict=True)
    source_general_contractor: str | None = Field(default=None, max_length=1000)
    general_contractor_id: int = Field(gt=0, strict=True)
    source_subcontractor: str | None = Field(default=None, max_length=1000)
    subcontractor_required: StrictBool = False
    subcontractor_id: int | None = Field(default=None, gt=0, strict=True)


@contextmanager
def connection(write=False, *, read_only=False, require_model=False):
    if write and read_only:
        raise ValueError('A read-only connection cannot be used for writing')
    if require_model and os.getenv('CONSTRUCTION_MODEL', 'legacy') != 'clean_start':
        raise HTTPException(403, 'CONSTRUCTION_MODEL=clean_start is required')
    database = os.getenv('CLEAN_START_DB_NAME', '')
    approved = database in {
        'ai_excel_agent_stage41210_20261014_1634',
        'ai_excel_agent_stage4151_20261019_86bf41ed',
    } or bool(
        re.fullmatch(r'ai_excel_agent_test_categories_[a-f0-9]{12}', database))
    if (os.getenv('APP_DB_PROFILE') != 'test'
            or os.getenv('CLEAN_START_DB_PROFILE') != 'test'
            or os.getenv('CLEAN_START_DB_SCHEMA') != 'public' or not approved):
        raise HTTPException(403, 'Clean-start API requires an explicitly allowed test database/profile/schema')
    config = {key: os.getenv('CLEAN_START_DB_' + key.upper()) for key in ('host', 'port', 'user', 'password')}
    if not all(config.values()):
        raise HTTPException(503, 'Clean-start connection configuration is incomplete')
    try:
        with psycopg.connect(**config, dbname=database, options='-c search_path=public -c lock_timeout=5000', row_factory=dict_row) as conn:
            if read_only:
                conn.execute('SET TRANSACTION READ ONLY')
            actual = conn.execute('SELECT current_database() AS db, current_schema() AS schema').fetchone()
            if actual != {'db': database, 'schema': 'public'}:
                raise HTTPException(403, 'Actual database/schema differs from the approved test environment')
            columns = {r['column_name'] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='construction_entities'")}
            if not {'entity_id', 'name', 'category_id', 'parent_entity_id', 'version'} <= columns or 'legacy_object_id' in columns:
                raise HTTPException(409, 'Clean-start schema with category correction is required')
            if require_model:
                from app.repositories.clean_construction_identity import validate, ModelUnavailable
                try:
                    validate(conn)
                except ModelUnavailable as error:
                    raise HTTPException(409, str(error)) from None
            if write:
                conn.execute('SELECT pg_advisory_xact_lock(20261014,25)')
            yield conn
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, 'An entity or alias with this normalized name already exists') from None
    except (psycopg.errors.ForeignKeyViolation, psycopg.errors.RestrictViolation):
        raise HTTPException(409, 'Unknown or referenced category/parent') from None
    except psycopg.errors.CheckViolation as error:
        raise HTTPException(409, error.diag.message_primary) from None
    except (psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure):
        raise HTTPException(409, 'Concurrent change; reload and retry') from None
    except psycopg.OperationalError:
        raise HTTPException(503, 'Clean-start test database is unavailable') from None


SELECT = '''SELECT e.*, p.name AS parent_name,
    COALESCE(p.is_archived,false) AS parent_is_archived,
    COALESCE(p.is_active,true) AS parent_is_active, c.name AS category_name
    FROM public.construction_entity_current e
    LEFT JOIN public.construction_entities p ON p.entity_id=e.parent_entity_id
    LEFT JOIN public.object_categories c ON c.id=e.category_id'''


def card(conn, entity_id):
    item = conn.execute(SELECT + ' WHERE e.entity_id=%s', (entity_id,)).fetchone()
    if item is None:
        raise HTTPException(404, 'Construction entity not found')
    return item


def checked(conn, entity_id, version):
    item = card(conn, entity_id)
    if item['version'] != version:
        raise HTTPException(409, 'Entity version changed; reload the card')
    return item


ALIAS_FIELDS = 'alias_id,entity_id,source_value,normalized_source_value,created_at'


def _alias_name(conn, source_value):
    normalized = conn.execute(
        "SELECT public.normalize_known_value('object', %s) AS normalized",
        (source_value,),
    ).fetchone()['normalized']
    if not normalized:
        raise HTTPException(400, 'Alternative name is empty after normalization')
    return normalized


def _alias_entity(conn, entity_id, *, lock=False):
    query = 'SELECT entity_id FROM public.construction_entities WHERE entity_id=%s'
    if lock:
        query += ' FOR KEY SHARE'
    if conn.execute(query, (entity_id,)).fetchone() is None:
        raise HTTPException(404, 'Construction entity not found')


def _ensure_alias_name_available(conn, normalized, *, alias_id=None):
    duplicate = conn.execute(
        '''SELECT alias_id FROM public.construction_entity_aliases
           WHERE normalized_source_value=%s
             AND (%s::bigint IS NULL OR alias_id<>%s)
           LIMIT 1''',
        (normalized, alias_id, alias_id),
    ).fetchone()
    if duplicate is not None:
        raise HTTPException(409, 'An alternative name with this normalized value already exists')


@router.get('/aliases')
def list_construction_aliases(entity_id: int | None = Query(default=None, gt=0)):
    with connection(read_only=True, require_model=True) as conn:
        if entity_id is not None:
            _alias_entity(conn, entity_id)
        rows = conn.execute(
            f'''SELECT {ALIAS_FIELDS}
                FROM public.construction_entity_aliases
                WHERE (%s::bigint IS NULL OR entity_id=%s)
                ORDER BY normalized_source_value,alias_id''',
            (entity_id, entity_id),
        ).fetchall()
        return {'status': 'ok', 'items': rows}


@router.post('/aliases', status_code=201)
def create_construction_alias(payload: ConstructionAliasInput):
    with connection(write=True, require_model=True) as conn:
        _alias_entity(conn, payload.entity_id, lock=True)
        normalized = _alias_name(conn, payload.source_value)
        _ensure_alias_name_available(conn, normalized)
        row = conn.execute(
            f'''INSERT INTO public.construction_entity_aliases(entity_id,source_value)
                VALUES (%s,%s)
                RETURNING {ALIAS_FIELDS}''',
            (payload.entity_id, payload.source_value),
        ).fetchone()
        return {'status': 'ok', 'item': row}


@router.patch('/aliases/{alias_id}')
def update_construction_alias(payload: ConstructionAliasInput, alias_id: int = Path(gt=0)):
    with connection(write=True, require_model=True) as conn:
        current = conn.execute(
            '''SELECT alias_id FROM public.construction_entity_aliases
               WHERE alias_id=%s FOR UPDATE''',
            (alias_id,),
        ).fetchone()
        if current is None:
            raise HTTPException(404, 'Construction alias not found')
        _alias_entity(conn, payload.entity_id, lock=True)
        normalized = _alias_name(conn, payload.source_value)
        _ensure_alias_name_available(conn, normalized, alias_id=alias_id)
        row = conn.execute(
            f'''UPDATE public.construction_entity_aliases
                SET entity_id=%s,source_value=%s
                WHERE alias_id=%s
                RETURNING {ALIAS_FIELDS}''',
            (payload.entity_id, payload.source_value, alias_id),
        ).fetchone()
        return {'status': 'ok', 'item': row}


@router.delete('/aliases/{alias_id}')
def delete_construction_alias(alias_id: int = Path(gt=0)):
    with connection(write=True, require_model=True) as conn:
        row = conn.execute(
            '''DELETE FROM public.construction_entity_aliases
               WHERE alias_id=%s RETURNING alias_id''',
            (alias_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, 'Construction alias not found')
        return {'status': 'ok', 'alias_id': row['alias_id'], 'deleted': True}


@router.get('/match')
def match_construction_entity(name: str = Query(min_length=1, max_length=1000)):
    with connection(read_only=True, require_model=True) as conn:
        normalized = _alias_name(conn, name)
        candidates = conn.execute(
            '''WITH matches AS (
                   SELECT e.entity_id,e.name,e.parent_entity_id,
                          e.is_active,e.is_archived,'name'::text AS source
                   FROM public.construction_entities e
                   WHERE public.normalize_known_value('object',e.name)=%s
                   UNION ALL
                   SELECT e.entity_id,e.name,e.parent_entity_id,
                          e.is_active,e.is_archived,'alias'::text AS source
                   FROM public.construction_entity_aliases a
                   JOIN public.construction_entities e ON e.entity_id=a.entity_id
                   WHERE a.normalized_source_value=%s
               )
               SELECT m.entity_id,m.name,m.parent_entity_id,p.name AS parent_name,
                      m.is_active,m.is_archived,
                      bool_or(m.source='name') AS exact_name_match,
                      bool_or(m.source='alias') AS alias_match
               FROM matches m
               LEFT JOIN public.construction_entities p ON p.entity_id=m.parent_entity_id
               GROUP BY m.entity_id,m.name,m.parent_entity_id,p.name,m.is_active,m.is_archived
               ORDER BY m.entity_id''',
            (normalized, normalized),
        ).fetchall()
        if not candidates:
            match = {'status': 'not_found'}
        elif len(candidates) > 1:
            match = {'status': 'ambiguous'}
        else:
            candidate = candidates[0]
            source = (
                'name_and_alias' if candidate['exact_name_match'] and candidate['alias_match']
                else 'name' if candidate['exact_name_match'] else 'alias'
            )
            match = {
                'status': 'found',
                'entity_id': candidate['entity_id'],
                'match_source': source,
                'item': candidate,
            }
        return {'status': 'ok', 'match': match, 'candidates': candidates}


@router.post('/word-report-match')
def match_word_report_object(payload: WordObjectMatchRequest):
    from app.services.clean_construction_matcher import match_word_object

    with connection(read_only=True, require_model=True) as conn:
        return {
            'status': 'ok',
            'match': match_word_object(conn, payload.object_name),
        }


@router.post('/word-report/parse')
async def parse_word_report(file: UploadFile = File(...)):
    from app.services.clean_word_report import (
        InvalidWordDocument,
        parse_clean_word_report,
    )

    filename = file.filename or 'report.docx'
    try:
        if not filename.lower().endswith('.docx'):
            raise HTTPException(415, 'Поддерживаются только файлы .docx')
        content = await file.read(MAX_WORD_REPORT_BYTES + 1)
        if not content:
            raise HTTPException(400, 'Файл пуст')
        if len(content) > MAX_WORD_REPORT_BYTES:
            raise HTTPException(413, 'Размер Word-файла превышает 10 МБ')
        try:
            with connection(read_only=True, require_model=True) as conn:
                report = parse_clean_word_report(conn, content, filename)
        except InvalidWordDocument:
            raise HTTPException(422, 'Не удалось прочитать Word-документ .docx') from None
        return {
            'status': 'ok',
            'intermediate_report': report,
            'errors': report['errors'],
            'persistence': {
                'daily_facts_written': False,
                'aliases_written': False,
            },
        }
    finally:
        await file.close()


@router.get('/word-report/dictionaries')
def clean_word_report_dictionaries():
    with connection(read_only=True, require_model=True) as conn:
        entities = conn.execute(
            '''SELECT e.entity_id,e.name,e.parent_entity_id,p.name AS parent_name,
                      e.is_active,e.is_archived
               FROM public.construction_entities e
               LEFT JOIN public.construction_entities p ON p.entity_id=e.parent_entity_id
               WHERE e.is_active AND NOT e.is_archived
                 AND (e.parent_entity_id IS NULL
                      OR (p.is_active AND NOT p.is_archived))
               ORDER BY p.name NULLS FIRST,e.name,e.entity_id'''
        ).fetchall()
        employees = conn.execute(
            '''SELECT e.id,e.full_name,e.position_id,p.name AS position_name
               FROM public.employees e
               LEFT JOIN public.positions p ON p.id=e.position_id
               WHERE NOT e.is_archived
               ORDER BY e.full_name,e.id'''
        ).fetchall()
        organizations = conn.execute(
            'SELECT id,name FROM public.po_types ORDER BY name,id'
        ).fetchall()
        return {
            'status': 'ok',
            'dictionaries': {
                'entities': entities,
                'employees': employees,
                'organizations': organizations,
            },
        }


@router.post('/word-report/confirm')
def confirm_word_report(payload: CleanWordReportConfirmation):
    if not payload.confirmed:
        raise HTTPException(409, 'Подтвердите проверку обязательных полей отчёта')
    absent_subcontractor_values = {'', '-', '–', '—', '−', '‑', '‒'}
    subcontractor_required = (
        payload.source_subcontractor is not None
        and payload.source_subcontractor.strip() not in absent_subcontractor_values
    )
    if payload.subcontractor_required != subcontractor_required:
        raise HTTPException(422, 'Статус обязательности субподрядчика не соответствует исходному полю')
    if subcontractor_required and payload.subcontractor_id is None:
        raise HTTPException(422, 'Выберите субподрядчика или отметьте его как отсутствующего')
    if not subcontractor_required and payload.subcontractor_id is not None:
        raise HTTPException(422, 'Для отсутствующего субподрядчика значение выбирать нельзя')

    with connection(read_only=True, require_model=True) as conn:
        employee = conn.execute(
            '''SELECT e.id,e.full_name,e.position_id,p.name AS position_name
               FROM public.employees e
               LEFT JOIN public.positions p ON p.id=e.position_id
               WHERE e.id=%s AND NOT e.is_archived''',
            (payload.employee_id,),
        ).fetchone()
        if employee is None:
            raise HTTPException(409, 'Выбранный сотрудник отсутствует или архивирован')

        entity = conn.execute(
            '''SELECT e.entity_id,e.name,e.parent_entity_id,e.activity_status,
                      e.is_active,e.is_archived,p.name AS parent_name,
                      p.is_active AS parent_is_active,p.is_archived AS parent_is_archived
               FROM public.construction_entities e
               LEFT JOIN public.construction_entities p ON p.entity_id=e.parent_entity_id
               WHERE e.entity_id=%s''',
            (payload.entity_id,),
        ).fetchone()
        if (entity is None or not entity['is_active'] or entity['is_archived']
                or (entity['parent_entity_id'] is not None
                    and (not entity['parent_is_active'] or entity['parent_is_archived']))):
            raise HTTPException(409, 'Выбранный объект отсутствует, архивирован или недоступен')

        general_contractor = conn.execute(
            'SELECT id,name FROM public.po_types WHERE id=%s',
            (payload.general_contractor_id,),
        ).fetchone()
        if general_contractor is None:
            raise HTTPException(409, 'Выбранный генподрядчик отсутствует в clean-start справочнике')

        subcontractor = None
        if payload.subcontractor_id is not None:
            subcontractor = conn.execute(
                'SELECT id,name FROM public.po_types WHERE id=%s',
                (payload.subcontractor_id,),
            ).fetchone()
            if subcontractor is None:
                raise HTTPException(409, 'Выбранный субподрядчик отсутствует в clean-start справочнике')

        parent = None
        if entity['parent_entity_id'] is not None:
            parent = {
                'entity_id': entity['parent_entity_id'],
                'name': entity['parent_name'],
            }
        confirmed_report = {
            'status': 'confirmed_pending_save',
            'report_date': payload.report_date.isoformat(),
            'employee': {
                'source_value': payload.source_full_name,
                'employee_id': employee['id'],
                'full_name': employee['full_name'],
                'position_name': employee['position_name'],
            },
            'construction_entity': {
                'source_value': payload.source_object_name,
                'entity_id': entity['entity_id'],
                'name': entity['name'],
                'kind': 'subobject' if parent else 'object',
                'parent': parent,
            },
            'general_contractor': {
                'source_value': payload.source_general_contractor,
                'id': general_contractor['id'],
                'name': general_contractor['name'],
            },
            'subcontractor': {
                'source_value': payload.source_subcontractor,
                'required': subcontractor_required,
                'id': subcontractor['id'] if subcontractor else None,
                'name': subcontractor['name'] if subcontractor else None,
            },
            'persistence': {
                'daily_facts_written': False,
                'aliases_written': False,
                'other_records_written': False,
            },
        }
        return {'status': 'ok', 'confirmed_report': confirmed_report}


@router.get('/environment')
def environment():
    with connection() as conn:
        actual = conn.execute('SELECT current_database() AS database, current_schema() AS schema').fetchone()
        return {'status': 'ok', 'item': {**actual, 'profile': 'test', 'contract': 'entity_id'}}


@router.get('/workspace')
def workspace(request: Request):
    from pathlib import Path as FilePath
    from fastapi.templating import Jinja2Templates
    with connection():
        templates = Jinja2Templates(directory=FilePath(__file__).resolve().parents[1] / 'templates')
        return templates.TemplateResponse(request=request, name='processing.html',
            context={'test_mode': True, 'clean_start': True})


@router.get('/word-report/workspace')
def word_report_workspace(request: Request):
    from pathlib import Path as FilePath
    from fastapi.templating import Jinja2Templates

    with connection(read_only=True, require_model=True):
        templates = Jinja2Templates(directory=FilePath(__file__).resolve().parents[1] / 'templates')
        return templates.TemplateResponse(
            request=request,
            name='clean_word_review.html',
            context={'test_mode': True, 'clean_start': True},
        )


@router.get('/categories')
def categories():
    with connection(read_only=True, require_model=True) as conn:
        return {'status': 'ok', 'items': conn.execute(
            'SELECT id,name,parent_id,sort_order,is_system FROM public.object_categories ORDER BY sort_order,id').fetchall()}


@router.get('/employees')
def employees(archive: Literal['active', 'archived', 'all'] = 'active'):
    with connection(read_only=True, require_model=True) as conn:
        return {'status': 'ok', 'items': conn.execute('''
            SELECT e.id,e.full_name,e.position_id,p.name AS position_name,e.is_archived,e.archived_at
            FROM public.employees e LEFT JOIN public.positions p ON p.id=e.position_id
            WHERE (%s='all' OR e.is_archived=(%s='archived')) ORDER BY e.full_name,e.id
            ''', (archive, archive)).fetchall()}


@router.get('/po-types')
def po_types():
    with connection(read_only=True, require_model=True) as conn:
        return {'status': 'ok', 'items': conn.execute(
            'SELECT id,name FROM public.po_types ORDER BY name,id').fetchall()}


@router.get('/employees/{employee_id}/assignments')
def employee_assignments(employee_id: int = Path(gt=0)):
    from app.repositories import clean_construction_assignments as assignments
    with connection(read_only=True, require_model=True) as conn:
        try:
            return {'status': 'ok', **assignments.list_for_employee(conn, employee_id)}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None


@router.post('/employees/{employee_id}/assignments', status_code=201)
def add_employee_assignment(payload: EmployeeAssignment, employee_id: int = Path(gt=0)):
    from app.repositories import clean_construction_assignments as assignments
    with connection(write=True, require_model=True) as conn:
        try:
            item = assignments.create(
                conn, employee_id, payload.entity_id, payload.po_id, payload.category_id
            )
            return {'status': 'ok', 'item': item}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None


@router.patch('/employees/{employee_id}/assignments/{assignment_id}')
def edit_employee_assignment(payload: EmployeeAssignment, employee_id: int = Path(gt=0),
                             assignment_id: int = Path(gt=0)):
    from app.repositories import clean_construction_assignments as assignments
    with connection(write=True, require_model=True) as conn:
        try:
            item = assignments.update(
                conn, employee_id, assignment_id, payload.entity_id, payload.po_id, payload.category_id
            )
            return {'status': 'ok', 'item': item}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None


@router.delete('/employees/{employee_id}/assignments/{assignment_id}')
def remove_employee_assignment(employee_id: int = Path(gt=0), assignment_id: int = Path(gt=0)):
    from app.repositories import clean_construction_assignments as assignments
    with connection(write=True, require_model=True) as conn:
        try:
            return {'status': 'ok', **assignments.delete(conn, employee_id, assignment_id)}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None


@router.get('')
def listing(kind: Literal['all', 'objects', 'subobjects'] = 'all',
            archive: Literal['all', 'active', 'archived'] = 'all',
            parent_entity_id: int | None = Query(None, gt=0),
            parents_for: int | None = Query(None, gt=0)):
    with connection() as conn:
        if parents_for is not None:
            card(conn, parents_for)
        if parent_entity_id is not None:
            card(conn, parent_entity_id)
        items = conn.execute(SELECT + ' ORDER BY e.name,e.entity_id').fetchall()
        items = [i for i in items
                 if (kind == 'all' or (i['parent_entity_id'] is None) == (kind == 'objects'))
                 and (parent_entity_id is None or i['parent_entity_id'] == parent_entity_id)
                 and (archive == 'all' or bool(i['is_archived'] or i['parent_is_archived']) == (archive == 'archived'))
                 and (parents_for is None or (i['parent_entity_id'] is None and i['entity_id'] != parents_for
                      and not i['is_archived'] and i['is_active']))]
        return {'status': 'ok', 'items': items}


@router.post('', status_code=201)
def create(payload: CreateEntity):
    with connection(write=True) as conn:
        entity_id = conn.execute('''INSERT INTO public.construction_entities
            (name, activity_status, category_id, parent_entity_id) VALUES (%s,%s,%s,%s) RETURNING entity_id''',
            (payload.name, payload.activity_status, payload.category_id, payload.parent_entity_id)).fetchone()['entity_id']
        return {'status': 'ok', 'item': card(conn, entity_id)}


@router.get('/{entity_id}')
def get_card(entity_id: int = Path(gt=0)):
    with connection() as conn:
        return {'status': 'ok', 'item': card(conn, entity_id)}


@router.patch('/{entity_id}')
def edit(payload: EditEntity, entity_id: int = Path(gt=0)):
    fields = payload.model_dump(exclude_unset=True, exclude={'version'})
    if not fields or any(fields.get(k) is None for k in ('name', 'activity_status') if k in fields):
        raise HTTPException(422, 'Provide name, activity_status or category_id; name/status cannot be null')
    with connection(write=True) as conn:
        checked(conn, entity_id, payload.version)
        from psycopg import sql
        conn.execute(sql.SQL('UPDATE public.construction_entities SET {} WHERE entity_id=%s').format(
            sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in fields)),
            (*fields.values(), entity_id))
        return {'status': 'ok', 'item': card(conn, entity_id)}


@router.patch('/{entity_id}/hierarchy')
def hierarchy(payload: Hierarchy, entity_id: int = Path(gt=0)):
    if not payload.confirmed:
        raise HTTPException(409, 'Confirmation is required')
    with connection(write=True) as conn:
        checked(conn, entity_id, payload.version)
        conn.execute('UPDATE public.construction_entities SET parent_entity_id=%s WHERE entity_id=%s',
                     (payload.parent_entity_id, entity_id))
        return {'status': 'ok', 'item': card(conn, entity_id)}


def archive_change(entity_id, payload, archived):
    with connection(write=True) as conn:
        item = checked(conn, entity_id, payload.version)
        if item['is_archived'] != archived:
            conn.execute('''UPDATE public.construction_entities SET is_archived=%s,
                archived_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END WHERE entity_id=%s''',
                (archived, archived, entity_id))
        return {'status': 'ok', 'item': card(conn, entity_id)}


@router.post('/{entity_id}/archive')
def archive_entity(payload: Version, entity_id: int = Path(gt=0)):
    return archive_change(entity_id, payload, True)


@router.post('/{entity_id}/restore')
def restore_entity(payload: Version, entity_id: int = Path(gt=0)):
    return archive_change(entity_id, payload, False)
