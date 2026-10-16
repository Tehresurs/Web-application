import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.repositories.daily_control import get_journal
from app.repositories.directory_errors import DirectoryConflict
from app.services.daily_control_service import ReviewRequest, review_result

router = APIRouter(prefix="/api/daily-control-results", tags=["Журнал контроля"])
logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field, ConfigDict
from app.database.db import get_connection
from app.repositories import report_review

class ReviewOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1)
    field: Literal['general_contractor','subcontractor'] | None = None
    as_rule: bool = False

class ReviewCategory(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1)
    employee_id: int = Field(gt=0)
    entity_id: int = Field(gt=0)
    po_id: int | None = Field(default=None,gt=0)
    category_id: int | None = Field(default=None,gt=0)
    automatic: bool = False

@router.post('/review-options')
def report_options(payload: ReviewOptions):
    try:
        with get_connection() as conn:
            if payload.field:
                item=report_review.approve(conn,payload.path,payload.field,payload.as_rule)
            else:
                digest,doc=report_review.source(payload.path)
                item=report_review.options(conn,digest,doc)
            return {'status':'ok',**item}
    except (ValueError,FileNotFoundError) as error:
        raise HTTPException(400,str(error)) from error

@router.get('/absence-rules')
def absence_rules():
    with get_connection() as conn:
        if not report_review.enabled(conn): return {'items':[]}
        return {'items':[dict(field=r[0],enabled=r[1],version=r[2]) for r in conn.execute('SELECT field,enabled,version FROM report_absence_rules ORDER BY field')]}

@router.delete('/absence-rules/{field}')
def cancel_absence_rule(field: Literal['general_contractor','subcontractor']):
    with get_connection() as conn:
        report_review.cancel_rule(conn,field)
    return {'status':'ok'}

@router.post('/review-category')
def review_category(payload: ReviewCategory):
    from psycopg.errors import ForeignKeyViolation,UniqueViolation,CheckViolation
    try:
        with get_connection() as conn:
            return {'status':'ok','item':report_review.category(conn,payload)}
    except (ValueError,DirectoryConflict) as error:
        raise HTTPException(409,str(error)) from error
    except (ForeignKeyViolation,UniqueViolation,CheckViolation) as error:
        raise HTTPException(409,'Не удалось сохранить категорию: '+(error.diag.message_primary or 'нарушено ограничение БД')) from error

@router.get('/review-assignments/{employee_id}')
def review_assignments(employee_id:int):
    from psycopg.rows import dict_row
    from app.repositories import construction_identity as identity
    with get_connection() as conn,conn.cursor(row_factory=dict_row) as cur:
        cur.execute('''SELECT a.*,p.name po_name,c.name category_name FROM employee_assignments a
            LEFT JOIN po_types p ON p.id=a.po_id LEFT JOIN object_categories c ON c.id=a.category_id
            WHERE employee_id=%s ORDER BY a.id''',(employee_id,))
        return {'items':[identity.describe(conn,dict(r)) for r in cur.fetchall()]}


def review_response(payload, save):
    try:
        result = review_result(payload, save=save)
    except DirectoryConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(400, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, "Нет доступа к исходному файлу") from error
    except Exception as error:
        logger.exception("Daily control review failed")
        raise HTTPException(500, "Не удалось проверить или сохранить отчёт") from error
    if save and not result["saved"]:
        raise HTTPException(409, jsonable_encoder({"message": "Замечания отчёта не устранены", **result}))
    return {"status": "ok", **result}


@router.post("/check")
def check_result(payload: ReviewRequest):
    return review_response(payload, False)


@router.post("")
def save_result(payload: ReviewRequest):
    return review_response(payload, True)


@router.get("")
def journal(
    date_from: date,
    date_to: date,
    employee_id: int | None = Query(default=None, gt=0),
    object_id: int | None = Query(default=None, gt=0),
    view: Literal["object", "employee"] = "object",
    subobject_id: int | None = Query(default=None, gt=0),
    include_subobjects: bool = True,
    subcontractor_id: int | None = Query(default=None, gt=0),
    entity_id: int | None = Query(default=None,gt=0),
):
    if date_from > date_to:
        raise HTTPException(400, "Начало периода должно быть не позже окончания")
    return {"status": "ok", "date_from": date_from, "date_to": date_to, "view": view,
            "filters": {"employee_id": employee_id, "object_id": object_id,
                        "subobject_id": subobject_id, "include_subobjects": include_subobjects, "subcontractor_id": subcontractor_id},
            **get_journal(date_from, date_to, employee_id, object_id, view,
                          subobject_id=subobject_id, include_subobjects=include_subobjects, subcontractor_id=subcontractor_id,entity_id=entity_id)}


@router.get('/facts/{fact_id}')
def matrix_fact_source(fact_id:int):
    from app.services.matrix_report_service import inspect_fact
    try:return {'status':'ok','item':inspect_fact(fact_id)}
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc


from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

@router.post('/upload-day')
async def upload_day(file:UploadFile=File(...),employee_id:int=Form(...),target:date=Form(...)):
    from app.services.matrix_report_service import upload_report
    content=await file.read(10*1024*1024+1)
    try:return {'status':'ok',**await run_in_threadpool(upload_report,content,file.filename,employee_id,target)}
    except (ValueError,DirectoryConflict) as exc:raise HTTPException(409,str(exc)) from exc

class DeleteMatrixFact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    employee_id: int = Field(gt=0)
    report_date: date
    source_sha256: str = Field(min_length=64,max_length=64)

@router.delete('/facts/{fact_id}')
def delete_matrix_fact(fact_id:int,payload:DeleteMatrixFact):
    from app.services.matrix_report_service import delete_fact
    try:return {'status':'ok',**delete_fact(fact_id,payload.employee_id,payload.report_date,payload.source_sha256)}
    except (ValueError,DirectoryConflict) as exc:raise HTTPException(409,str(exc)) from exc

@router.post('/upload-file')
async def upload_single_report(file:UploadFile=File(...)):
    from app.services.matrix_report_service import upload_report
    content=await file.read(10*1024*1024+1)
    try:return {'status':'ok',**await run_in_threadpool(upload_report,content,file.filename)}
    except (ValueError,DirectoryConflict) as exc:raise HTTPException(409,str(exc)) from exc
