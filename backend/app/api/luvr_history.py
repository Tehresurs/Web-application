from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, NaiveDatetime, field_validator, model_validator

from app.repositories import luvr_history

router = APIRouter(prefix="/api/employees/{employee_id}/luvr", tags=["История ЛУВР"])
MovementType = Literal["ARRIVAL", "DEPARTURE"]
TransportType = Literal["RAIL", "SELF"]
ExceptionType = Literal["SHIFT", "OFF_SHIFT"]
DayValue = Literal["FULL", "HALF", "TRAVEL", "OFF_SHIFT", "DOWNTIME", "DISMISSED", "EMPTY"]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MovementRequest(RequestModel):
    movement_type: MovementType
    transport_type: TransportType
    event_datetime: NaiveDatetime
    departure_station: str | None = None
    arrival_station: str | None = None
    source_file: str | None = None

    @field_validator("event_datetime", mode="before")
    @classmethod
    def local_datetime(cls, value):
        if not isinstance(value, (str, datetime)) or (isinstance(value, str) and "T" not in value and " " not in value):
            raise ValueError("Укажите местные дату и время")
        return value


class MovementPatch(MovementRequest):
    movement_type: MovementType | None = None
    transport_type: TransportType | None = None
    event_datetime: NaiveDatetime | None = None

    @model_validator(mode="after")
    def changes(self):
        _check_patch(self, {"movement_type", "transport_type", "event_datetime"})
        return self


class SickPeriodRequest(RequestModel):
    date_from: date
    date_to: date | None = None
    comment: str | None = None


class SickPeriodPatch(SickPeriodRequest):
    date_from: date | None = None

    @model_validator(mode="after")
    def changes(self):
        _check_patch(self, {"date_from"})
        return self


class DurationExceptionRequest(RequestModel):
    exception_type: ExceptionType
    date_from: date
    date_to: date
    comment: str


class DurationExceptionPatch(DurationExceptionRequest):
    exception_type: ExceptionType | None = None
    date_from: date | None = None
    date_to: date | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def changes(self):
        _check_patch(self, {"exception_type", "date_from", "date_to", "comment"})
        return self


class DayOverrideRequest(RequestModel):
    work_date: date
    value: DayValue
    comment: str | None = None


def _check_patch(model, required):
    if not model.model_fields_set or any(getattr(model, f) is None for f in model.model_fields_set & required):
        raise ValueError("Укажите изменяемые поля; обязательные поля нельзя очистить")


class StoredRecord(BaseModel):
    id: int
    employee_id: int
    created_at: datetime
    updated_at: datetime


class Movement(StoredRecord, MovementRequest):
    confirmed_ticket_id: int | None = None


class SickPeriod(StoredRecord, SickPeriodRequest):
    pass


class DurationException(StoredRecord, DurationExceptionRequest):
    pass


class DayOverride(StoredRecord, DayOverrideRequest):
    pass


T = TypeVar("T")


class ItemResponse(BaseModel, Generic[T]):
    status: Literal["ok"] = "ok"
    item: T


class ListResponse(BaseModel, Generic[T]):
    status: Literal["ok"] = "ok"
    items: list[T]


class DeleteResponse(BaseModel):
    status: Literal["ok"] = "ok"
    id: int
    deleted: bool


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str


class MovementDeleteResponse(DeleteResponse):
    ticket_id: int | None = None


router.responses = {code: {"model": ErrorResponse} for code in (400, 404)}


def _response(operation, *args, key="item", **kwargs):
    try:
        result = operation(*args, **kwargs)
        return {"status": "ok", key: result} if key else {"status": "ok", **result}
    except ValueError as error:
        return JSONResponse(status_code=getattr(error, "status_code", 400), content={"status": "error", "message": str(error)})


@router.get("/movements", response_model=ListResponse[Movement])
def list_movements(employee_id: int = Path(gt=0), date_from: date | None = None, date_to: date | None = None):
    return _response(luvr_history.get_history, "movements", employee_id, date_from, date_to, key="items")


@router.post("/movements", response_model=ItemResponse[Movement])
def create_movements(payload: MovementRequest, employee_id: int = Path(gt=0)):
    return _response(luvr_history.create_history, "movements", employee_id, **payload.model_dump())


@router.patch("/movements/{item_id}", response_model=ItemResponse[Movement])
def update_movements(payload: MovementPatch, employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.update_history, "movements", employee_id, item_id, **payload.model_dump(exclude_unset=True))


@router.delete("/movements/{item_id}", response_model=MovementDeleteResponse, response_model_exclude_none=True,
               responses={409:{'model':ErrorResponse}})
def delete_movements(employee_id: int = Path(gt=0), item_id: int = Path(gt=0),
                     delete_ticket: bool = Query(False,description='Явное удаление ЖД-события вместе с конкретным билетом-источником')):
    return _response(luvr_history.delete_history, "movements", employee_id, item_id, delete_ticket=delete_ticket, key=None)


@router.get("/sick-periods", response_model=ListResponse[SickPeriod])
def list_sick_periods(employee_id: int = Path(gt=0), date_from: date | None = None, date_to: date | None = None):
    return _response(luvr_history.get_history, "sick-periods", employee_id, date_from, date_to, key="items")


@router.post("/sick-periods", response_model=ItemResponse[SickPeriod])
def create_sick_periods(payload: SickPeriodRequest, employee_id: int = Path(gt=0)):
    return _response(luvr_history.create_history, "sick-periods", employee_id, **payload.model_dump())


@router.patch("/sick-periods/{item_id}", response_model=ItemResponse[SickPeriod])
def update_sick_periods(payload: SickPeriodPatch, employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.update_history, "sick-periods", employee_id, item_id, **payload.model_dump(exclude_unset=True))


@router.delete("/sick-periods/{item_id}", response_model=DeleteResponse)
def delete_sick_periods(employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.delete_history, "sick-periods", employee_id, item_id, key=None)


@router.get("/duration-exceptions", response_model=ListResponse[DurationException])
def list_duration_exceptions(employee_id: int = Path(gt=0), date_from: date | None = None, date_to: date | None = None):
    return _response(luvr_history.get_history, "duration-exceptions", employee_id, date_from, date_to, key="items")


@router.post("/duration-exceptions", response_model=ItemResponse[DurationException])
def create_duration_exceptions(payload: DurationExceptionRequest, employee_id: int = Path(gt=0)):
    return _response(luvr_history.create_history, "duration-exceptions", employee_id, **payload.model_dump())


@router.patch("/duration-exceptions/{item_id}", response_model=ItemResponse[DurationException])
def update_duration_exceptions(payload: DurationExceptionPatch, employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.update_history, "duration-exceptions", employee_id, item_id, **payload.model_dump(exclude_unset=True))


@router.delete("/duration-exceptions/{item_id}", response_model=DeleteResponse)
def delete_duration_exceptions(employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.delete_history, "duration-exceptions", employee_id, item_id, key=None)


@router.get("/day-overrides", response_model=ListResponse[DayOverride])
def list_day_overrides(employee_id: int = Path(gt=0), date_from: date | None = None, date_to: date | None = None):
    return _response(luvr_history.get_history, "day-overrides", employee_id, date_from, date_to, key="items")


@router.post("/day-overrides", response_model=ItemResponse[DayOverride])
def create_day_overrides(payload: DayOverrideRequest, employee_id: int = Path(gt=0)):
    return _response(luvr_history.create_history, "day-overrides", employee_id, **payload.model_dump())


@router.delete("/day-overrides/{item_id}", response_model=DeleteResponse)
def delete_day_overrides(employee_id: int = Path(gt=0), item_id: int = Path(gt=0)):
    return _response(luvr_history.delete_history, "day-overrides", employee_id, item_id, key=None)
