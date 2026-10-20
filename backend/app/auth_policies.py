"""Audited explicit route policies. No method-based permission inference."""
import json
from pathlib import Path
from starlette.routing import Mount

def routes(app):
    def walk(items):
        for r in items:
            if hasattr(r,'original_router'):yield from walk(r.original_router.routes)
            else:yield r
    return list(walk(app.routes))

def identity(route):
    if isinstance(route,Mount):
        return type(route.app).__module__+'.'+type(route.app).__qualname__+':'+str(getattr(route.app,'directory',''))
    f=getattr(route,'endpoint',None)
    return getattr(f,'__module__','')+'.'+getattr(f,'__qualname__','')

def policies():
    return json.loads(Path(__file__).with_name('auth_route_policies.json').read_text(encoding='utf-8'))

async def validate_payload(guard,request):
    if guard=='single_ticket_file':
        from starlette.datastructures import UploadFile
        async with request.form(max_files=1,max_fields=0) as form:
            entries=list(form.multi_items())
            if len(entries)!=1 or entries[0][0]!='files' or not isinstance(entries[0][1],UploadFile):
                raise ValueError('Only one ticket file per operation')
        return
    data=await request.json()
    if not isinstance(data,dict):raise ValueError('Object required')
    if guard=='daily_no_replace':
        if any(data.get(k) is not None for k in ('replace_fact_id','replacement_token','replace_source_sha256')) or data.get('confirm_replacement',False) is not False:
            raise ValueError('Replacement may delete facts/overrides')
    elif guard=='review_no_approval':
        if data.get('field') is not None or data.get('as_rule',False) is not False:
            raise ValueError('Approval/rule changes forbidden')
    else:raise ValueError('Unknown payload policy')
