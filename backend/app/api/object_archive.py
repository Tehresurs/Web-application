from typing import Literal
from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict
from app.api.known_values import _response
from app.repositories.object_archive import change

router=APIRouter(prefix='/api',tags=['Архив объектов'])
Kind=Literal['objects','subobjects']

class StatusRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    activity_status: Literal['ACTIVE','SUSPENDED','COMPLETED']

def register(kind):
    def archive(item_id:int=Path(gt=0),id_type:Literal['legacy','entity']='legacy'):
        if id_type=='entity':
            from app.api.construction_identity import change_entity
            return _response(change_entity,item_id,is_archived=True)
        return _response(change,kind,item_id,is_archived=True)
    def restore(item_id:int=Path(gt=0),id_type:Literal['legacy','entity']='legacy'):
        if id_type=='entity':
            from app.api.construction_identity import change_entity
            return _response(change_entity,item_id,is_archived=False)
        return _response(change,kind,item_id,is_archived=False)
    def status(payload:StatusRequest,item_id:int=Path(gt=0),id_type:Literal['legacy','entity']='legacy'):
        if id_type=='entity':
            from app.api.construction_identity import change_entity
            return _response(change_entity,item_id,activity_status=payload.activity_status)
        return _response(change,kind,item_id,activity_status=payload.activity_status)
    router.add_api_route('/'+kind+'/{item_id}/archive',archive,methods=['POST'],name=kind+'_archive')
    router.add_api_route('/'+kind+'/{item_id}/restore',restore,methods=['POST'],name=kind+'_restore')
    router.add_api_route('/'+kind+'/{item_id}/activity-status',status,methods=['PATCH'],name=kind+'_status')

for kind in ('objects','subobjects'):
    register(kind)
