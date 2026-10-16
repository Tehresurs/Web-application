from fastapi import APIRouter, Query
from app.api.luvr_history import _response
from app.services.production_matrix import calculate_month

router = APIRouter(tags=['Производственная матрица'])


@router.get('/api/production-matrix')
def matrix(year: int=Query(ge=1900,le=9999),month: int=Query(ge=1,le=12),employee_id: int | None=Query(default=None,gt=0)):
    return _response(calculate_month,year,month,employee_id)
