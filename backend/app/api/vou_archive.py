from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,ConfigDict
from app.services.vou_report import generate
from app.services.vou_excel_com import ExcelComError
from app.services.vou_data import VouDataError, describe_vou_issue
from app.services.vou_archive import VouArchive

router=APIRouter(prefix='/api/vou/reports',tags=['Архив Отчета ВОУ'])
archive=VouArchive()


@router.get('')
def reports():
    return {'status':'ok',**archive.list_reports()}


def read_report(report_id):
    try:
        return archive.read(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(404,'Архивный отчёт не найден') from exc
    except (ValueError,KeyError,OSError) as exc:
        raise HTTPException(409,'Архивный отчёт недоступен или повреждён') from exc


@router.get('/{report_id}')
def report_metadata(report_id:str):
    metadata,_=read_report(report_id)
    return {'status':'ok','item':metadata}


@router.get('/{report_id}/file')
def report_file(report_id:str):
    metadata,path=read_report(report_id)
    return FileResponse(path,media_type='application/vnd.ms-excel.sheet.macroEnabled.12',
                        filename=metadata['filename'])


class GenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    year:int=Field(ge=1900,le=9999)
    month:int=Field(ge=1,le=12)


@router.post('')
def generate_report(body:GenerateRequest):
    try:
        result=generate(body.year,body.month)
        return {'status':'ok',**result}
    except VouDataError as exc:
        errors = [dict(code=issue['code'], details=issue['details'],
                       message=describe_vou_issue(issue)) for issue in exc.issues]
        raise HTTPException(409,{'message':'Данные ВОУ требуют проверки','code':exc.code,
                                 'details':exc.details,'errors':errors}) from exc
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except ExcelComError as exc:
        raise HTTPException(503,str(exc)) from exc
