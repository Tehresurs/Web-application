from datetime import datetime
from typing import Literal
import logging

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from app.repositories import rail_tickets
from app.services.rail_ticket_service import process_document, upload_error
from app.services.rail_ticket_parser import MAX_TICKET_BYTES

router=APIRouter(prefix="/api/rail-tickets",tags=["ЖД-билеты ЛУВР"])
log=logging.getLogger(__name__)


class TicketMovement(BaseModel):
    id: int
    employee_id: int
    movement_type: Literal["ARRIVAL","DEPARTURE"]
    transport_type: Literal["RAIL"]
    event_datetime: datetime
    departure_station: str | None
    arrival_station: str | None
    source_file: str | None


class RailTicket(BaseModel):
    id: int | None = None
    file_hash: str | None = None
    source_filename: str
    source_page: int | None = None
    source_sha256: str | None = None
    full_name: str | None = None
    full_name_raw: str | None = None
    departure_station: str | None = None
    departure_datetime: datetime | None = None
    arrival_station: str | None = None
    arrival_datetime: datetime | None = None
    parse_errors: list[str] = []
    status: Literal["PARSED","PARSE_ERROR","REJECTED","CONFIRMED"] | None = None
    processing_status: Literal["EMPLOYEE_NOT_FOUND","ARCHIVED_EMPLOYEE","NEEDS_DIRECTION","READY","CONFIRMED","PARSE_ERROR","DUPLICATE","REJECTED","UNSUPPORTED","NOT_LUVR_ROUTE"]
    notice: str | None = None
    is_luvr_route: bool | None = None
    direction_candidate: Literal["ARRIVAL","DEPARTURE"] | None = None
    match_status: Literal["FOUND","NOT_FOUND"]
    match_ambiguous: bool = False
    employee_id: int | None = None
    employee_name: str | None = None
    employee_is_archived: bool = False
    movement_type: Literal["ARRIVAL","DEPARTURE"] | None = None
    movement_id: int | None = None
    movement: TicketMovement | None = None
    duplicate: bool = False


class TicketResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item: RailTicket


class UploadResponse(BaseModel):
    status: Literal["ok"] = "ok"
    items: list[RailTicket]


class DirectionRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    movement_type: Literal["ARRIVAL","DEPARTURE"]


class ConfirmRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")


def _response(operation,*args):
    try:return {"status":"ok","item":operation(*args)}
    except ValueError as error:
        return JSONResponse(status_code=getattr(error,"status_code",400),content={"status":"error","message":str(error)})


@router.post("/upload",response_model=UploadResponse,summary="Загрузить PDF из папки или Drag & Drop: без создания событий")
async def upload_tickets(files: list[UploadFile] = File(...)):
    results=[];total=0
    try:
        if len(files)>50:
            return JSONResponse(status_code=400,content={"status":"error","message":"За один раз можно загрузить не более 50 файлов"})
        for file in files:
            name=file.filename or "ticket.pdf"
            try:
                data=await file.read(MAX_TICKET_BYTES+1);total+=len(data)
                if not data:
                    results.append(upload_error(name,"Файл пуст"));continue
                if len(data)>MAX_TICKET_BYTES or total>50*1024*1024:
                    results.append(upload_error(name,"Превышен размер: до 10 МБ на файл и до 50 МБ на пакет"));continue
                results.extend(await run_in_threadpool(process_document,data,name))
            except Exception:
                # Never log PDF text, passport fields or raw parsing exceptions.
                log.error("RAIL_FILE_PROCESSING_FAILED")
                results.append(upload_error(name,"Не удалось обработать файл. Попробуйте загрузить его ещё раз."))
        return {"status":"ok","items":results}
    finally:
        for file in files:await file.close()


@router.get("/{ticket_id}",response_model=TicketResponse,summary="Получить сохранённый разбор и повторить точное сопоставление ФИО")
def get_ticket(ticket_id: int):return _response(rail_tickets.get_ticket,ticket_id)


@router.patch("/{ticket_id}/direction",response_model=TicketResponse,deprecated=True,summary="Совместимость: ручное изменение автоматического направления запрещено")
def set_direction(ticket_id: int,payload: DirectionRequest):return _response(rail_tickets.choose_direction,ticket_id,payload.movement_type)


@router.post("/{ticket_id}/confirm",response_model=TicketResponse,summary="Атомарно создать одно RAIL-событие подтверждённого билета")
def confirm(ticket_id: int,payload: ConfirmRequest):return _response(rail_tickets.confirm_ticket,ticket_id)


@router.post("/{ticket_id}/reject",response_model=TicketResponse)
def reject(ticket_id: int,payload: ConfirmRequest):return _response(rail_tickets.reject_ticket,ticket_id)
