from datetime import date
from typing import Literal
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, PositiveInt, model_validator
from app.api.luvr_history import _response
from app.repositories import production_assignments as repository

router = APIRouter(tags=['Производственные назначения'])


class AssignmentItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    object_id: PositiveInt | None = None
    entity_id: PositiveInt | None = None
    subobject_id: PositiveInt | None = None
    po_id: PositiveInt | None = None
    subcontractor_id: PositiveInt | None = None
    initial_category_id: PositiveInt | None = None
    initial_control_mode: Literal['INSPECTION', 'OPERATIONAL', 'GEODETIC'] | None = None
    source_assignment_id: PositiveInt | None = None

    @model_validator(mode='after')
    def reference_required(self):
        if self.entity_id is None and self.object_id is None:
            raise ValueError('Укажите entity_id или object_id')
        return self


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    effective_from: date
    period_kind: Literal['ARRIVAL', 'EXPLICIT'] = 'ARRIVAL'
    arrival_movement_ref: PositiveInt | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_kind: Literal['MANUAL', 'TICKET'] = 'MANUAL'
    source_ticket_id: PositiveInt | None = None
    assignment_state: Literal['OBJECTS', 'NO_OBJECT']
    items: list[AssignmentItem]

    @model_validator(mode='after')
    def coherent(self):
        if (self.assignment_state == 'OBJECTS') != bool(self.items):
            raise ValueError('OBJECTS требует объекты; NO_OBJECT требует пустой список')
        if self.period_kind == 'ARRIVAL':
            if not self.arrival_movement_ref or self.period_start is not None or self.period_end is not None:
                raise ValueError('Период ARRIVAL определяется движением, без ручных границ')
        elif self.arrival_movement_ref or not self.period_start or not self.period_end or not self.period_start <= self.effective_from <= self.period_end:
            raise ValueError('Укажите корректные границы явного периода')
        if self.source_kind == 'TICKET':
            if not self.source_ticket_id or self.period_kind != 'ARRIVAL' or self.assignment_state != 'OBJECTS':
                raise ValueError('Источник TICKET требует билет заезда и объекты')
        elif self.source_ticket_id is not None:
            raise ValueError('Ручное назначение не имеет source_ticket_id')
        keys = [(i.entity_id, i.object_id, i.subobject_id, i.po_id, i.subcontractor_id) for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError('Объекты в наборе повторяются')
        return self


class AssignmentCorrection(AssignmentRequest):
    version: PositiveInt


@router.get('/api/employees/{employee_id}/production-assignments')
def history(employee_id: int = Path(gt=0), date_from: date = Query(), date_to: date = Query()):
    return _response(repository.get_history, employee_id, date_from, date_to)


@router.post('/api/employees/{employee_id}/production-assignments')
def create(payload: AssignmentRequest, employee_id: int = Path(gt=0)):
    data=payload.model_dump()
    for source,item in zip(payload.items,data['items']):
        if 'initial_control_mode' not in source.model_fields_set:item.pop('initial_control_mode')
    return _response(repository.save, employee_id, data)


@router.patch('/api/production-assignments/{change_id}')
def correct(payload: AssignmentCorrection, change_id: int = Path(gt=0)):
    return _response(repository.correct, change_id, payload.model_dump(exclude={'version'}), payload.version)
