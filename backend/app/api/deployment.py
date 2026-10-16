from datetime import date as Date
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from app.services.deployment import get_report
from app.services.deployment_excel import export_report
from app.services.deployment_analysis import get_analysis

router=APIRouter(prefix='/api/deployment',tags=['Расстановка'])


@router.get('/analysis')
def analysis(date: Date):
    if date < Date(1900,1,8):
        raise HTTPException(422,'Дата анализа должна быть не раньше 08.01.1900')
    return {'status':'ok','item':get_analysis(date)}


@router.get('/report')
def report(date: Date):
    return {'status':'ok','item':get_report(date)}


@router.get('/report/export')
def export(date: Date, include_analysis: bool = False):
    data=get_report(date)
    if not data['formed']:
        raise HTTPException(409,'ЛУВР на выбранный месяц не сформирован')
    if include_analysis and date < Date(1900,1,8):
        raise HTTPException(422,'Дата анализа должна быть не раньше 08.01.1900')
    analysis_data=get_analysis(date) if include_analysis else None
    return Response(export_report(data, analysis=analysis_data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f'Расстановка_{date.isoformat()}.xlsx')})
