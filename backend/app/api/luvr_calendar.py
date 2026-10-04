from datetime import date
from typing import Literal
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel
from app.api.luvr_history import DayValue, ItemResponse, _response
from app.repositories.luvr_calendar import get_calendar_inputs
from app.services.luvr_calendar import calculate_employee_day, calculate_employee_month

router=APIRouter(prefix='/api/employees/{employee_id}/luvr',tags=['Календарь ЛУВР'])


class CalendarWarning(BaseModel):
    code: str
    message: str
    movement_ids: list[int]


class CalendarDay(BaseModel):
    date: date
    auto_code: DayValue
    auto_display: str
    final_code: DayValue
    final_display: str
    manually_changed: bool
    is_sick: bool
    movement_ids: list[int]
    warnings: list[CalendarWarning]
    state: Literal['UNKNOWN','ON_SHIFT','OFF_SHIFT']
    calculation_status: Literal['UNKNOWN','CALCULATED','NEEDS_REVIEW']
    source_type: str
    final_source_type: str
    override_id: int | None
    override_code: DayValue | None
    override_comment: str | None


class EmployeeCalendar(BaseModel):
    employee_id: int
    full_name: str
    work_location: str | None
    work_schedule: str | None
    is_archived: bool
    dismissal_date: date | None
    year: int
    month: int
    mode: Literal['SHIFT','FIVE_TWO','CONFIGURATION_ERROR','UNKNOWN_WORK_SCHEDULE']
    days: list[CalendarDay]


def month_calendar(employee_id,year,month):
    return calculate_employee_month(get_calendar_inputs(employee_id),year,month)


def day_calendar(employee_id,target):
    return calculate_employee_day(get_calendar_inputs(employee_id),target)


@router.get('/calendar',response_model=ItemResponse[EmployeeCalendar],summary='Расчёт календаря без изменения истории и БД')
def get_month(employee_id: int=Path(gt=0),year: int=Query(ge=1,le=9999),month: int=Query(ge=1,le=12)):
    return _response(month_calendar,employee_id,year,month)


@router.get('/calendar/day',response_model=ItemResponse[CalendarDay],summary='Расчёт дня по тем же правилам, что и месяц')
def get_day(target: date,employee_id: int=Path(gt=0)):
    return _response(day_calendar,employee_id,target)
