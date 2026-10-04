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
):
    if date_from > date_to:
        raise HTTPException(400, "Начало периода должно быть не позже окончания")
    return {"status": "ok", "date_from": date_from, "date_to": date_to, "view": view,
            "filters": {"employee_id": employee_id, "object_id": object_id,
                        "subobject_id": subobject_id, "include_subobjects": include_subobjects, "subcontractor_id": subcontractor_id},
            **get_journal(date_from, date_to, employee_id, object_id, view,
                          subobject_id=subobject_id, include_subobjects=include_subobjects, subcontractor_id=subcontractor_id)}
