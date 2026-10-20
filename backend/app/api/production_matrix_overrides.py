from datetime import date
from typing import Literal
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator
from app.api.luvr_history import _response
from app.repositories import production_matrix_overrides as repository

router = APIRouter(tags=['Корректировки производственной матрицы'])


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    effective_from: date
    scope: Literal['FACT','PLAN']
    field_name: Literal['CATEGORY','CONTROL_MODE','PO']
    category_id: PositiveInt | None = None
    po_id: PositiveInt | None = None
    control_mode: Literal['INSPECTION','OPERATIONAL','GEODETIC'] | None = None
    fact_id: PositiveInt | None = None
    assignment_item_id: PositiveInt | None = None
    period_key: str = Field(min_length=1,max_length=250)
    basis_revision: str = Field(min_length=1,max_length=100)
    version: int = Field(ge=0,strict=True)

    @model_validator(mode='after')
    def valid_change(self):
        if (self.fact_id is None) == (self.assignment_item_id is None):
            raise ValueError('Укажите ровно один источник: факт или строку назначения')
        if self.scope == 'FACT' and self.fact_id is None:
            raise ValueError('FACT требует подтверждённый факт')
        if self.field_name == 'PO':
            if self.po_id is None or self.category_id is not None or self.control_mode is not None:
                raise ValueError('PO изменяет только ПО')
            return self
        if self.po_id is not None:raise ValueError('ПО изменяется отдельной корректировкой')
        if self.field_name == 'CATEGORY':
            if self.category_id is None or self.control_mode is not None:
                raise ValueError('CATEGORY изменяет только категорию')
        elif self.control_mode is None or self.category_id is not None:
            raise ValueError('CONTROL_MODE изменяет только режим')
        return self


@router.get('/api/employees/{employee_id}/production-matrix-overrides')
def get_overrides(employee_id: int=Path(gt=0),date_from: date=Query(),date_to: date=Query(),period_key: str | None=Query(default=None)):
    return _response(repository.get_overrides,employee_id,date_from,date_to,period_key)


@router.patch('/api/employees/{employee_id}/production-matrix-overrides')
def upsert(payload: OverrideRequest,employee_id: int=Path(gt=0)):
    return _response(repository.upsert,employee_id,payload.model_dump())


@router.delete('/api/production-matrix-overrides/{override_id}')
def remove(override_id: int=Path(gt=0),version: int=Query(gt=0)):
    return _response(repository.remove,override_id,version)
