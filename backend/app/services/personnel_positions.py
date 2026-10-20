"""Dated read-model shared by future calendar/report adapters.
No alternative calendar calculation and no silently selected pre-history policy.
"""
from datetime import date
from app.repositories.directory_errors import DirectoryConflict
# Candidate dependencies only; this does not register them in the signed DK protocol.
PERSONNEL_CONTEXT_TABLES=('personnel_position_baselines','personnel_position_definitions','personnel_position_events','personnel_position_state','personnel_settings','personnel_acting_events')
DEFINITION_FIELDS=('specialty','work_location','work_schedule','requires_daily_report','action_description','report_description','aos_description','equipment_description','planned_count')
class PositionHistoryUnavailable(DirectoryConflict):pass

def _date(value):return value if isinstance(value,date) else date.fromisoformat(value)

def position_on(inputs,target):
    """Return a copy; never change employee identity, crew, category or sources.
    The caller must load all context from one DB snapshot. No DB/global clock here.
    """
    context=inputs.get('personnel_context')
    if context is None:return dict(inputs)
    day=_date(target);periods=context['periods'];chosen=next((p for p in periods if _date(p['known_from'])<=day and (not p['known_to'] or day<_date(p['known_to']))),None)
    status='KNOWN'
    if chosen is None:
        policy=context['legacy_history_policy']
        if policy!='LEGACY_WITH_WARNING':
            raise PositionHistoryUnavailable('Основная должность на дату '+str(day)+' документально не известна')
        # The pre-existing card is the compatibility source, not an unverified transfer.
        # Its initial appointment date remains unknown; no historical row is created.
        chosen={'position_id':context['baseline']['position_id']};status='EXISTING_CARD'
    pid=chosen['position_id'];result=dict(inputs)
    result['position_id']=pid;result['position_history_status']=status
    if pid is None:
        result['position_name']=None;result['position_definition_version_id']=None
        result.update({key:None for key in DEFINITION_FIELDS});result['position_history_status']='UNKNOWN_POSITION';return result
    versions=[v for v in context['definitions'] if v['position_id']==pid]
    available=[v for v in versions if _date(v['known_from'])<=day]
    if available:version=max(available,key=lambda v:(_date(v['known_from']),v['id']))
    elif context['legacy_history_policy']=='LEGACY_WITH_WARNING' and versions:
        version=min(versions,key=lambda v:(_date(v['known_from']),v['id']))
        status='EXISTING_CARD' if pid==context['baseline']['position_id'] and (status=='EXISTING_CARD' or chosen.get('effective_start_unknown')) else ('EXISTING_DIRECTORY' if version.get('start_unknown') else 'LEGACY_UNVERIFIED')
        result['position_history_status']=status
    else:raise PositionHistoryUnavailable('Свойства должности на дату '+str(day)+' неизвестны')
    definition=version['definition'];result['position_name']=definition['name'];result['position_definition_version_id']=version['id']
    result.update({key:definition.get(key) for key in DEFINITION_FIELDS})
    if chosen.get('retained_report_requirement'):result['requires_daily_report']=True
    result.update(chosen.get('retained_calendar_configuration') or {})
    if status in ('EXISTING_CARD','EXISTING_DIRECTORY'):result['position_effective_start_unknown']=True
    if status=='LEGACY_UNVERIFIED':result['position_history_warning']='История должности не подтверждена; использовано исходное наблюдение'
    return result

def calendar_position(inputs,target):
    """Adapter input for the existing calendar/eligible, not a second algorithm."""
    return position_on(inputs,target)


def acting_on(inputs,target):
    day=_date(target);context=inputs.get('personnel_context')
    if context is None:return None
    matches=[a for a in context.get('acting',[]) if _date(a['starts_on'])<=day<=_date(a['ends_on'])]
    if len(matches)>1:raise PositionHistoryUnavailable('На дату действуют пересекающиеся И.О.')
    if not matches:return None
    item=matches[0]
    versions=[v for v in context['definitions'] if v['position_id']==item['position_id'] and _date(v['known_from'])<=day]
    if not versions:raise PositionHistoryUnavailable('Параметры временной должности на дату неизвестны')
    version=max(versions,key=lambda v:(_date(v['known_from']),v['id']))
    return {**item,'definition':version['definition'],'definition_version_id':version['id']}

def dated_personnel(inputs,target):
    main=position_on(inputs,target);acting=acting_on(inputs,target)
    main['acting_assignment']=acting
    expired=[a for a in inputs.get('personnel_context',{}).get('acting',[]) if _date(a['ends_on'])<_date(target) and a.get('kind')!='END']
    main['return_plan_required']=bool(not acting and expired)
    main['return_plan_from']=max((_date(a['ends_on']) for a in expired),default=None)
    main['display_position_name']=acting_label(acting['definition']['name']) if acting else main.get('position_name')
    # Keep original calendar/rotation settings and primary position identity.
    main['engineering_report_required']=bool(acting['definition'].get('requires_daily_report')) if acting else bool(main.get('requires_daily_report'))
    return main

def split_luvr_rows(row,inputs):
    """Presentation partition of existing FULL/HALF cells, never another calendar."""
    from copy import deepcopy
    if not inputs.get('personnel_context'):return [row]
    main=deepcopy(row);main['row_key']='employee:'+str(row['employee_id']);lanes={}
    for index,day in enumerate(row['days']):
        acting=acting_on(inputs,day['date'])
        if not acting:continue
        key=str(acting['root_id'])
        if key not in lanes:
            lane=deepcopy(row);lane['row_key']='acting:'+key;lane['position_name']=acting_label(acting['definition']['name']);lane['full_name']=row['full_name'];lane['acting_root_id']=key
            lane['days']=[{**d,'final_code':'EMPTY','final_display':'','auto_code':'EMPTY','auto_display':'','is_sick':False,'manually_changed':False,'final_source_type':'PERSONNEL_PROJECTION','warnings':[]} for d in row['days']]
            lanes[key]=lane
        if day['final_code'] in ('FULL','HALF'):
            lanes[key]['days'][index]=deepcopy(day)
            main['days'][index].update(final_code='EMPTY',final_display='',final_source_type='ACTING_ROW',is_sick=False,manually_changed=False)
    return [main,*lanes.values()]


def acting_label(name):
    import re
    if ' '.join(name.split()).casefold()=='руководитель ск':return 'И.О. Руководителя СК'
    return name if re.match(r'^И[.\s]*О[.\s]',name,re.IGNORECASE) else 'И.О. '+name
