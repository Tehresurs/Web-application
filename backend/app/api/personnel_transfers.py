"""Personnel endpoints enforce sessions even when called through app.main directly."""
from uuid import UUID
from datetime import date
from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field,PositiveInt
from app.api import user_auth
from app.services.user_auth import AuthDenied
from app.repositories import personnel_transfers as repository
from app.services import personnel_local

router=APIRouter(prefix='/api/employees/{employee_id}/position-transfers',tags=['Кадровые переводы'])
class TransferRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    position_id:PositiveInt
    effective_on:date=Field(ge=date(1900,1,1),le=date(9999,12,30))
    source_position_id:PositiveInt|None=None
    reason:str|None=Field(default=None,max_length=2000)
    request_id:UUID
    expected_version:int=Field(ge=0)
class ReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    position_id:PositiveInt|None=None
    effective_on:date|None=None
    reason:str=Field(min_length=1,max_length=2000)
    request_id:UUID
    expected_version:int=Field(ge=0)

def session(request,write=False):
    local=personnel_local.authorize(request,write)
    if local is not None:return local
    if write:return user_auth.require_session_csrf(request)
    user_auth.transport(request)
    try:user=user_auth.service().current(request.cookies.get(user_auth.COOKIE))
    except AuthDenied:raise HTTPException(401,'Требуется вход в систему') from None
    except Exception:raise HTTPException(503,'Сервис авторизации недоступен') from None
    if 'data.read' not in user['permissions']:raise HTTPException(403,'Просмотр недоступен')
    return user

def respond(action):
    try:return {'status':'ok','item':action()}
    except PermissionError as error:raise HTTPException(403,str(error)) from None
    except ValueError as error:raise HTTPException(getattr(error,'status_code',400),str(error)) from None

@router.get('/capabilities')
def capabilities(employee_id:int,request:Request):
    user=session(request)
    result=respond(lambda:repository.capabilities(user))
    if personnel_local.is_local(user):result['item']['local_request_token']=personnel_local.browser_key()
    from fastapi.responses import JSONResponse
    return JSONResponse(result,headers={'Cache-Control':'no-store','Vary':'Sec-Fetch-Site','X-Content-Type-Options':'nosniff'})
@router.get('')
def history(employee_id:int,request:Request):
    session(request);return respond(lambda:repository.history(employee_id))
@router.post('')
def transfer(employee_id:int,payload:TransferRequest,request:Request):
    user=session(request,True);caps=repository.capabilities(user)
    if caps['read_only']:raise HTTPException(403,'Оформление перевода недоступно')
    return respond(lambda:repository.execute(user,employee_id,payload))
@router.post('/{root_id}/corrections')
def correct(employee_id:int,root_id:UUID,payload:ReviewRequest,request:Request):
    user=session(request,True)
    if not repository.capabilities(user)['can_review']:raise HTTPException(403,'Исправление доступно только определённому Создателю')
    return respond(lambda:repository.execute(user,employee_id,payload,operation='CORRECT',target=root_id))
@router.post('/{root_id}/cancellations')
def cancel(employee_id:int,root_id:UUID,payload:ReviewRequest,request:Request):
    user=session(request,True)
    if not repository.capabilities(user)['can_review']:raise HTTPException(403,'Отмена доступна только определённому Создателю')
    if payload.position_id is not None or payload.effective_on is not None:raise HTTPException(422,'При отмене новая должность и дата не задаются')
    return respond(lambda:repository.execute(user,employee_id,payload,operation='CANCEL',target=root_id))


from app.api.production_assignments import AssignmentRequest
class ActingRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    position_id:PositiveInt
    starts_on:date=Field(ge=date(1900,1,1),le=date(9999,12,30))
    ends_on:date=Field(ge=date(1900,1,1),le=date(9999,12,30))
    reason:str|None=Field(default=None,max_length=2000)
    request_id:UUID
    expected_version:int=Field(ge=0)
class ActingEndRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ends_on:date=Field(ge=date(1900,1,1),le=date(9999,12,30))
    reason:str=Field(min_length=1,max_length=2000)
    plan:AssignmentRequest
    request_id:UUID
    expected_version:int=Field(ge=0)
class ActingReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ends_on:date|None=None
    reason:str=Field(min_length=1,max_length=2000)
    request_id:UUID
    expected_version:int=Field(ge=0)

def acting_writer(request,review=False):
    user=session(request,True);caps=repository.capabilities(user)
    if caps['read_only'] or (review and not caps['can_review']):raise HTTPException(403,'Кадровая операция недоступна')
    return user

@router.post('/acting')
def assign_acting(employee_id:int,payload:ActingRequest,request:Request):
    user=acting_writer(request)
    if payload.ends_on<payload.starts_on:raise HTTPException(422,'Дата окончания раньше начала')
    return respond(lambda:repository.execute_acting(user,employee_id,payload))

@router.post('/acting/{root_id}/end')
def end_acting(employee_id:int,root_id:UUID,payload:ActingEndRequest,request:Request):
    user=acting_writer(request)
    return respond(lambda:repository.execute_acting(user,employee_id,payload,operation='END',target=root_id))

@router.post('/acting/{root_id}/end-date')
def change_acting_end(employee_id:int,root_id:UUID,payload:ActingReviewRequest,request:Request):
    user=acting_writer(request,True)
    if payload.ends_on is None:raise HTTPException(422,'Укажите новую дату окончания')
    return respond(lambda:repository.execute_acting(user,employee_id,payload,operation='CHANGE_END',target=root_id))

@router.post('/acting/{root_id}/cancel')
def cancel_acting(employee_id:int,root_id:UUID,payload:ActingReviewRequest,request:Request):
    user=acting_writer(request,True)
    if payload.ends_on is not None:raise HTTPException(422,'Отмена не задаёт дату окончания')
    return respond(lambda:repository.execute_acting(user,employee_id,payload,operation='CANCEL',target=root_id))


@router.get('/planning-context')
def planning_context(employee_id:int,on_day:date,request:Request):
    session(request)
    return respond(lambda:repository.planning_context(employee_id,on_day))


@router.get('/predecessor')
def predecessor(employee_id:int,on_day:date,request:Request):
    session(request)
    return respond(lambda:repository.predecessor(employee_id,on_day))
