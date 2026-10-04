from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.repositories import subobjects, value_aliases
from app.services.reference_service import require_subobject, require_value_alias


router = APIRouter(prefix="/api", tags=["Подобъекты и соответствия"])
EntityType = Literal["employee", "object", "subobject", "po", "subcontractor"]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSubobjectRequest(RequestModel):
    object_id: int = Field(gt=0)
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Название не заполнено")
        return value


class UpdateSubobjectRequest(RequestModel):
    name: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Укажите name или is_active; null не допускается")
        if self.name is not None and not self.name.strip():
            raise ValueError("Название не заполнено")
        return self


class CreateAliasRequest(RequestModel):
    entity_type: EntityType
    source_value: str = Field(min_length=1)
    target_id: int = Field(gt=0)


    @field_validator("source_value")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Исходное значение не заполнено")
        return value


class UpdateAliasRequest(RequestModel):
    target_id: int = Field(gt=0)


class MoveSubobjectRequest(RequestModel):
    object_id: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class ConfirmSubobjectMoveRequest(MoveSubobjectRequest):
    confirmation_token: str | None = None


class SubobjectMovePreview(BaseModel):
    subobject_id: int
    name: str
    is_active: bool
    old_object_id: int
    old_object_name: str
    object_id: int
    object_name: str
    linked_facts: int
    missing_assignments: int
    confirmation_token: str
    requires_confirmation: bool


class SubobjectMovePreviewResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item: SubobjectMovePreview


class Subobject(BaseModel):
    id: int
    object_id: int
    name: str
    is_active: bool
    object_name: str


class ValueAlias(BaseModel):
    id: int
    entity_type: EntityType
    source_value: str
    normalized_source_value: str
    target_id: int
    target_name: str | None
    target_exists: bool
    target_is_active: bool | None
    object_id: int | None = None
    object_name: str | None = None


class SubobjectResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item: Subobject


class SubobjectsResponse(BaseModel):
    status: Literal["ok"] = "ok"
    items: list[Subobject]


class SubobjectMoveResponse(SubobjectResponse):
    updated_facts: int
    missing_assignments: int


class AliasResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item: ValueAlias


class CreateAliasResponse(AliasResponse):
    created: bool


class AliasesResponse(BaseModel):
    status: Literal["ok"] = "ok"
    items: list[ValueAlias]


class DeleteResponse(BaseModel):
    status: Literal["ok"] = "ok"
    id: int
    deleted: bool


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str


router.responses = {code: {"model": ErrorResponse} for code in (400, 404, 409)}


def _response(operation, *args, key="item", **kwargs):
    try:
        result = operation(*args, **kwargs)
        return {"status": "ok", key: result} if key else {"status": "ok", **result}
    except ValueError as error:
        return JSONResponse(status_code=getattr(error, "status_code", 400),
                            content={"status": "error", "message": str(error)})


@router.get("/subobjects", response_model=SubobjectsResponse, summary="Активные подобъекты")
def list_subobjects(object_id: int | None = Query(default=None, gt=0), include_inactive: bool = False):
    return _response(subobjects.get_subobjects, object_id, include_inactive, key="items")


@router.get("/subobjects/{subobject_id}", response_model=SubobjectResponse, summary="Подобъект по ID, включая неактивный")
def get_subobject(subobject_id: int):
    return _response(require_subobject, subobject_id)


@router.post("/subobjects", response_model=SubobjectResponse, summary="Создать подобъект")
def create_subobject(payload: CreateSubobjectRequest):
    return _response(subobjects.create_subobject, **payload.model_dump())


@router.patch("/subobjects/{subobject_id}", response_model=SubobjectResponse, summary="Переименовать или деактивировать подобъект")
def update_subobject(subobject_id: int, payload: UpdateSubobjectRequest):
    return _response(subobjects.update_subobject, subobject_id, **payload.model_dump(exclude_unset=True))


@router.get("/value-aliases", response_model=AliasesResponse, summary="Соответствия: точный поиск по нормализованному значению")
def list_aliases(entity_type: EntityType | None = None, source_value: str | None = None):
    return _response(value_aliases.get_value_aliases, entity_type, source_value, key="items")


@router.post("/subobjects/{subobject_id}/move/check", response_model=SubobjectMovePreviewResponse,
             summary="Проверить перенос подобъекта без изменения данных")
def check_subobject_move(subobject_id: int, payload: MoveSubobjectRequest):
    return _response(subobjects.preview_subobject_move, subobject_id, **payload.model_dump())


@router.patch("/subobjects/{subobject_id}/move", response_model=SubobjectMoveResponse,
              summary="Атомарно перенести подобъект и связанные факты контроля")
def transfer_subobject(subobject_id: int, payload: ConfirmSubobjectMoveRequest):
    return _response(subobjects.move_subobject, subobject_id, key=None, **payload.model_dump())


@router.get("/value-aliases/{alias_id}", response_model=AliasResponse, summary="Соответствие по ID")
def get_alias(alias_id: int):
    return _response(require_value_alias, alias_id)


@router.post("/value-aliases", response_model=CreateAliasResponse, summary="Создать соответствие без автоматической замены")
def create_alias(payload: CreateAliasRequest):
    return _response(value_aliases.create_value_alias, key=None, **payload.model_dump())


@router.patch("/value-aliases/{alias_id}", response_model=AliasResponse, summary="Явно изменить целевую запись")
def update_alias(alias_id: int, payload: UpdateAliasRequest):
    return _response(value_aliases.update_value_alias_target, alias_id, payload.target_id)


@router.delete("/value-aliases/{alias_id}", response_model=DeleteResponse, summary="Удалить соответствие")
def delete_alias(alias_id: int):
    return _response(value_aliases.delete_value_alias, alias_id, key=None)
