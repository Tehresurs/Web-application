from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.services import vou_settings

router = APIRouter(prefix='/api/vou', tags=['Отчет ВОУ'])


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    contract_number: str = Field(max_length=500)
    contract_date: date | None = None
    contract_revision: str = Field(max_length=500)
    customer_signer_name: str = Field(max_length=500)
    contractor_signer_name: str = Field(max_length=500)


@router.get('/settings')
def get_settings():
    return {'status': 'ok', 'item': vou_settings.get_settings()}


@router.put('/settings')
def put_settings(body: SettingsRequest):
    try:
        return {'status': 'ok', 'item': vou_settings.save_settings(body.model_dump())}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
