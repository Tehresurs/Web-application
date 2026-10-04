from datetime import date
from typing import Literal
from pydantic import BaseModel
from app.api.luvr_calendar import CalendarWarning


class DurationException(BaseModel):
    id: int
    exception_type: Literal['SHIFT','OFF_SHIFT']
    date_from: date
    date_to: date
    comment: str


class DurationSickPeriod(BaseModel):
    id: int
    date_from: date
    date_to: date | None
    comment: str | None


class DurationStatus(BaseModel):
    current_state: Literal['ON_SHIFT','OFF_SHIFT','UNKNOWN','DISMISSED','NOT_APPLICABLE']
    state_since: date | None
    as_of_date: date
    current_duration_days: int | None
    current_shift_days: int | None
    current_off_shift_days: int | None
    max_shift_days: int | None
    max_off_shift_days: int | None
    maximum_days: int | None
    ratio: float | None
    indicator_status: Literal['NORMAL','WARNING_50','MAX_REACHED','EXCEEDED','APPROVED_EXTENSION','NONE','UNKNOWN']
    indicator_enabled: bool
    is_sick: bool
    active_exception: DurationException | None
    active_exceptions: list[DurationException]
    sick_periods: list[DurationSickPeriod]
    excluded_sick_days: int
    movement_id: int | None
    warnings: list[CalendarWarning]
