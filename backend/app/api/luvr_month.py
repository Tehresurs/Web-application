from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field, StrictInt
from fastapi.responses import Response, JSONResponse
from app.services.luvr_export_footer import export_final_month as export_month
from app.api.luvr_calendar import EmployeeCalendar
from app.api.luvr_duration import DurationStatus
from app.api.luvr_history import ItemResponse, RequestModel, _response
from app.repositories import luvr_month
from app.services.luvr_month import month_calendar

router=APIRouter(prefix='/api/luvr/month',tags=['Месячный ЛУВР'])


@router.get('/export', response_class=Response, responses={200: {'content': {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {}}}})
def download_month(year: int=Query(ge=1900,le=9999), month: int=Query(ge=1,le=12)):
    return _download_month(year,month)


class OrderedExportRequest(RequestModel):
    year: int=Field(ge=1900,le=9999)
    month: int=Field(ge=1,le=12)
    employee_ids: list[StrictInt]


@router.post('/export',response_class=Response,responses={200:{'content':{'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':{}}}})
def download_ordered_month(body: OrderedExportRequest):
    return _download_month(body.year,body.month,body.employee_ids)


def _download_month(year,month,employee_ids=None):
    try:
        content = export_month(year, month, employee_ids)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={'status': 'error', 'message': str(exc)})
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="LUVR_{year}-{month:02d}.xlsx"; filename*=UTF-8\'\'{quote(f"ЛУВР_{year}-{month:02d}.xlsx")}'})


class HeaderSettings(RequestModel):
    approver_position: str=Field(min_length=1,max_length=1000)
    approver_name: str=Field(min_length=1,max_length=1000)
    document_title: str=Field(min_length=1,max_length=15000)
    developer_position: str=Field(min_length=1,max_length=1000)
    developer_name: str=Field(min_length=1,max_length=1000)
    agreed_position: str=Field(min_length=1,max_length=1000)
    agreed_name: str=Field(min_length=1,max_length=1000)
    legend: str=Field(min_length=1,max_length=15000)


class HeaderSettingsView(HeaderSettings):
    # An unconfigured signature can be displayed, but cannot be saved/exported.
    agreed_name: str | None


@router.get('/settings',response_model=ItemResponse[HeaderSettingsView])
def header_settings():
    return _response(luvr_month.get_settings)


@router.put('/settings',response_model=ItemResponse[HeaderSettings])
def save_header_settings(body: HeaderSettings):
    return _response(luvr_month.update_settings,**body.model_dump())


@router.get('/header-snapshot')
def header_snapshot(year: int=Query(ge=1,le=9999),month: int=Query(ge=1,le=12)):
    return _response(luvr_month.get_header_snapshot,year,month)


class MonthRequest(RequestModel):
    year: int=Field(ge=1,le=9999)
    month: int=Field(ge=1,le=12)


class MemberRequest(MonthRequest):
    employee_id: int=Field(gt=0)


class Totals(BaseModel):
    work_days_total: float
    travel_days_total: int
    off_shift_days_total: int
    downtime_days_total: int
    manual_changes_count: int
    sick_days_count: int


class MonthEmployee(EmployeeCalendar):
    position_name: str | None
    specialty: str | None
    nrs_number: str | None
    totals: Totals
    duration: DurationStatus


class DayTotals(BaseModel):
    date: date
    full_count: int
    half_count: int
    travel_count: int
    off_shift_count: int
    downtime_count: int
    dismissed_count: int
    sick_count: int
    unknown_count: int
    present_people_count: int
    work_equivalent: float


class MonthCalendar(MonthRequest):
    days_in_month: int
    formed: bool
    employees: list[MonthEmployee]
    as_of_date: date
    is_projection: bool
    day_totals: list[DayTotals]


class MembershipResult(BaseModel):
    formed: bool


@router.get('',response_model=ItemResponse[MonthCalendar])
def get_month(year: int=Query(ge=1,le=9999),month: int=Query(ge=1,le=12),
              as_of_date: date | None=Query(default=None,description='Контрольная дата состояния. Будущая явная дата — прогноз.')):
    return _response(month_calendar,year,month,as_of_date)


@router.post('/form',response_model=ItemResponse[MembershipResult])
def form_month(body: MonthRequest):
    return _response(luvr_month.form_month,body.year,body.month)


@router.post('/employees',response_model=ItemResponse[MembershipResult])
def add_member(body: MemberRequest):
    return _response(luvr_month.change_member,body.year,body.month,body.employee_id)


@router.delete('/employees/{employee_id}',response_model=ItemResponse[MembershipResult])
def remove_member(employee_id: int=Path(gt=0),year: int=Query(ge=1,le=9999),month: int=Query(ge=1,le=12)):
    return _response(luvr_month.change_member,year,month,employee_id,remove=True)
