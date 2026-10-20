from datetime import date
from fastapi import APIRouter, HTTPException, Path
from app.services import matrix_dk
from app.repositories.directory_errors import DirectoryConflict

router=APIRouter(tags=['ДК — Дубль-контроль'])

@router.get('/api/production-matrix/capabilities')
def capabilities():
    return {'status':'ok','item':matrix_dk.capabilities()}

def change(employee_id,target,enabled):
    try:return {'status':'ok','item':matrix_dk.set_event(employee_id,target,enabled)}
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
    except (ValueError,DirectoryConflict) as exc:raise HTTPException(409,str(exc)) from exc

@router.put('/api/employees/{employee_id}/production-matrix/dk/{target}')
def assign(target:date,employee_id:int=Path(gt=0)):
    return change(employee_id,target,True)

@router.delete('/api/employees/{employee_id}/production-matrix/dk/{target}')
def cancel(target:date,employee_id:int=Path(gt=0)):
    return change(employee_id,target,False)
