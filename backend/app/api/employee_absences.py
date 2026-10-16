from datetime import date
from typing import Literal
from fastapi import APIRouter,Path
from pydantic import BaseModel,ConfigDict,Field
from app.api.luvr_history import _response,ItemResponse,ListResponse,DeleteResponse
from app.repositories import employee_absences

router=APIRouter(prefix='/api/employees/{employee_id}/absences',tags=['Отсутствия сотрудников'])


class AbsenceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason: str=Field(min_length=1,max_length=500)
    date_from: date
    date_to: date | None
    comment: str | None=None


class Absence(AbsenceRequest):
    id: int
    employee_id: int
    source: Literal['other','sick']


@router.get('',response_model=ListResponse[Absence])
def list_absences(employee_id:int=Path(gt=0)):
    return _response(employee_absences.list_absences,employee_id,key='items')


@router.post('',response_model=ItemResponse[Absence])
def create_absence(payload:AbsenceRequest,employee_id:int=Path(gt=0)):
    return _response(employee_absences.save_absence,employee_id,**payload.model_dump())


@router.patch('/{source}/{item_id}',response_model=ItemResponse[Absence])
def edit_absence(payload:AbsenceRequest,source:Literal['other','sick'],employee_id:int=Path(gt=0),item_id:int=Path(gt=0)):
    return _response(employee_absences.save_absence,employee_id,source=source,item_id=item_id,**payload.model_dump())


@router.delete('/{source}/{item_id}',response_model=DeleteResponse)
def remove_absence(source:Literal['other','sick'],employee_id:int=Path(gt=0),item_id:int=Path(gt=0)):
    return _response(employee_absences.delete_absence,employee_id,source,item_id,key=None)
