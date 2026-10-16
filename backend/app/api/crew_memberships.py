from typing import Annotated
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.repositories import crew_memberships
from app.repositories.directory_errors import DirectoryConflict, DirectoryNotFound

router = APIRouter(prefix='/api/crew-memberships', tags=['Состав экипажей'])
Identifier = Annotated[int, Field(strict=True, gt=0)]


class EmployeeLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    employee_id: Identifier
    expected_crew_id: Identifier | None


class MembershipChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_crew_id: Identifier | None
    employees: list[EmployeeLink] = Field(min_length=1, max_length=1000)
    confirm_transfers: StrictBool = False


@router.patch('')
def change_memberships(payload: MembershipChange):
    try:
        return {'items': crew_memberships.change_memberships(**payload.model_dump())}
    except (DirectoryConflict, DirectoryNotFound) as error:
        return JSONResponse(status_code=error.status_code, content={'message': str(error)})
    except ValueError as error:
        return JSONResponse(status_code=400, content={'message': str(error)})
