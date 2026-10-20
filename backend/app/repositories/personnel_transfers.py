"""Named personnel operations. No startup DDL, employee UPDATE or role creation."""
from datetime import date
from psycopg.rows import dict_row
from app.database.db import get_connection
from app.services.luvr_duration import local_today
from app.services import personnel_local
from app.repositories.directory_errors import DirectoryConflict,DirectoryNotFound

POSITION_FIELDS=('action_description','specialty','work_location','work_schedule','requires_daily_report','report_description','aos_description','equipment_description','planned_count')
def installed(connection):
    return connection.execute("SELECT to_regclass('personnel_settings') IS NOT NULL").fetchone()[0]
def settings(connection):
    if not installed(connection):return None
    with connection.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT * FROM personnel_settings WHERE id=1');return cur.fetchone()
def blockers(config,local=False):
    if config is None:return ['История переводов ещё не установлена']
    result=[]
    if not config['enabled']:result.append('Кадровая запись пока не включена')
    if not local and not config['dk_context_verified']:result.append('Расширенный контекст ДК ещё не проверен')
    if not config['date_readers_verified']:result.append('Исторические расчёты ещё не подключены')
    if config['legacy_history_policy']=='UNRESOLVED':result.append('Не выбрано правило расчёта неизвестной истории')
    return result

def capabilities(user):
    with get_connection() as c:cfg=settings(c)
    if personnel_local.is_local(user):
        reasons=blockers(cfg,True)
        if not cfg or not cfg.get('local_enabled'):reasons.append('Локальный кадровый режим выключен')
        return {'installed':cfg is not None,'can_transfer':not reasons,'can_review':not reasons,'read_only':False,'blockers':reasons,'can_acting':not reasons,'audit_source':'LOCAL_APP'}
    roles=set(user['roles']);creator=bool(cfg and cfg['creator_user_id']==user['id'])
    writer=creator or ('SYSTEM_TECHNICIAN' in roles and 'data.update' in user['permissions'])
    reasons=blockers(cfg)
    return {'installed':cfg is not None,'can_transfer':writer and not reasons,'can_review':creator and not reasons,'read_only':not writer,'blockers':reasons,'can_acting':writer and not reasons}

def history(employee_id):
    with get_connection() as c:
        if not c.execute('SELECT 1 FROM employees WHERE id=%s',(employee_id,)).fetchone():raise DirectoryNotFound('Сотрудник не найден')
        if not installed(c):return {'installed':False,'version':0,'periods':[],'audit':[],'current':None}
        with c.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT version FROM personnel_position_state WHERE employee_id=%s',(employee_id,));state=cur.fetchone()
            cur.execute('SELECT * FROM personnel_position_baselines WHERE employee_id=%s',(employee_id,));baseline=cur.fetchone()
            if baseline is not None:
                cur.execute('SELECT definition FROM personnel_position_definitions WHERE position_id=%s AND known_from<=%s AND recorded_at<=%s ORDER BY known_from DESC,id DESC LIMIT 1',(baseline['position_id'],baseline['known_on'],baseline['observed_at']))
                observed=cur.fetchone();baseline['definition']=observed['definition'] if observed else None
            cur.execute('SELECT p.*,personnel_position_at(p.employee_id,p.known_from) AS position FROM personnel_position_periods p WHERE employee_id=%s ORDER BY known_from',(employee_id,));periods=cur.fetchall()
            cur.execute("SELECT e.*,CASE WHEN e.audit_source='LOCAL_APP' THEN 'Локальное приложение' ELSE u.login END AS actor_login FROM personnel_position_events e LEFT JOIN auth_users u ON u.id=e.actor_user_id WHERE e.employee_id=%s ORDER BY version",(employee_id,));audit=cur.fetchall()
            cur.execute('SELECT personnel_position_at(%s,%s) AS value',(employee_id,local_today()));current=cur.fetchone()['value']
        acting=[]
        if c.execute("SELECT to_regclass('personnel_acting_events')").fetchone()[0]:
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute("""SELECT a.*,CASE WHEN a.audit_source='LOCAL_APP' THEN 'Локальное приложение' ELSE u.login END AS actor_login,coalesce(d.definition->>'name',p.name) AS position_name FROM personnel_acting_events a LEFT JOIN auth_users u ON u.id=a.actor_user_id JOIN positions p ON p.id=a.position_id LEFT JOIN LATERAL (SELECT definition FROM personnel_position_definitions WHERE position_id=a.position_id AND known_from<=a.starts_on AND recorded_at<=a.recorded_at ORDER BY known_from DESC,id DESC LIMIT 1) d ON true WHERE a.employee_id=%s ORDER BY a.version""",(employee_id,));acting=cur.fetchall()
        return {'installed':True,'version':state['version'],'baseline':baseline,'periods':periods,'audit':audit,'current':current,'acting_audit':acting}

def execute(user,employee_id,payload,*,operation='TRANSFER',target=None):
    import psycopg
    try:
        with get_connection() as c:
            if blockers(settings(c),personnel_local.is_local(user)):raise DirectoryConflict('; '.join(blockers(settings(c),personnel_local.is_local(user))))
            if personnel_local.is_local(user):
                row=c.execute('SELECT personnel_local_position_command(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(personnel_local.sql_key(),employee_id,payload.position_id,payload.effective_on,payload.reason,payload.request_id,payload.expected_version,operation,target,getattr(payload,'source_position_id',None))).fetchone()
            elif operation=='TRANSFER':
                row=c.execute('SELECT personnel_transfer_with_source(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(user['id'],user['session_id'],employee_id,payload.position_id,payload.effective_on,payload.reason,payload.request_id,payload.expected_version,payload.source_position_id)).fetchone()
            else:
                row=c.execute('SELECT personnel_review_transfer(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(user['id'],user['session_id'],employee_id,payload.position_id,payload.effective_on,payload.reason,payload.request_id,payload.expected_version,operation,target)).fetchone()
            return row[0]
    except psycopg.Error as error:
        message=error.diag.message_primary or 'Кадровая операция не выполнена'
        if error.sqlstate=='42501':raise PermissionError(message) from None
        if error.sqlstate=='P0002':raise DirectoryNotFound(message) from None
        if error.sqlstate in ('22023','23505','23514','40001','55P03','55000'):raise DirectoryConflict(message) from None
        raise

def current_positions(connection,items):
    if not items or not installed(connection):return items
    # Same transaction/snapshot as the employee list; no background cache writer.
    found=connection.execute('SELECT e.id,personnel_position_at(e.id,%s) FROM employees e WHERE e.id=ANY(%s)',(local_today(),[r['id'] for r in items])).fetchall()
    by_id=dict(found)
    for item in items:
        value=by_id[item['id']]
        if value['status']=='KNOWN' and value['definition_status']=='KNOWN':
            definition=value['definition'];item['position_id']=value['position_id'];item['position_name']=definition['name']
            item.update({k:definition.get(k) for k in POSITION_FIELDS})
        item['position_history_status']=value['status'];item['personnel_history_installed']=True
    return items


def execute_acting(user,employee_id,payload,*,operation='ASSIGN',target=None):
    """Reuse assignment.save on this exact connection; no secondary commit."""
    import psycopg
    from psycopg.types.json import Jsonb
    from app.repositories.production_assignments import save
    values=payload.model_dump(mode='json')
    plan=values.get('plan')
    canonical={'employee_id':employee_id,'position_id':values.get('position_id'),'starts_on':values.get('starts_on'),'ends_on':values.get('ends_on'),'reason':(values.get('reason') or '').strip() or None,'operation':operation,'target':str(target) if target else None,'plan':plan}
    try:
        with get_connection() as c:
            if blockers(settings(c),personnel_local.is_local(user)):raise DirectoryConflict('; '.join(blockers(settings(c),personnel_local.is_local(user))))
            for a,b in ((20261017,29),(20261007,1601),(20261013,24)):c.execute('SELECT pg_advisory_xact_lock(%s,%s)',(a,b))
            if personnel_local.is_local(user):
                c.execute('SELECT personnel_local_admit(%s)',(personnel_local.sql_key(),))
                old=c.execute("SELECT payload,result FROM personnel_position_requests WHERE audit_source='LOCAL_APP' AND actor_user_id IS NULL AND request_id=%s",(payload.request_id,)).fetchone()
                if old:
                    if old[0]!=canonical:raise DirectoryConflict('request_id уже использован с другими данными')
                    return old[1]
            else:
                allowed=c.execute("""SELECT EXISTS(SELECT 1 FROM auth_users u JOIN auth_sessions s ON s.user_id=u.id
                  WHERE u.id=%s AND NOT u.is_blocked AND s.id=%s AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND s.credential_version=u.credential_version
                  AND (EXISTS(SELECT 1 FROM personnel_settings WHERE id=1 AND creator_user_id=u.id) OR EXISTS(
                    SELECT 1 FROM auth_user_roles ur JOIN auth_roles r ON r.id=ur.role_id JOIN auth_role_permissions rp ON rp.role_id=r.id JOIN auth_permissions p ON p.id=rp.permission_id WHERE ur.user_id=u.id AND r.code='SYSTEM_TECHNICIAN' AND p.code='data.update')))""",(user['id'],user['session_id'])).fetchone()[0]
                if not allowed:raise PermissionError('Кадровая операция недоступна')
                if operation in ('CANCEL','CHANGE_END') and not capabilities_on_connection(c,user)['can_review']:raise PermissionError('Исправление или отмена недоступны')
                if not c.execute("SELECT to_regclass('personnel_acting_events')").fetchone()[0]:raise DirectoryConflict('Журнал И.О. ещё не установлен')
                old=c.execute('SELECT payload,result FROM personnel_position_requests WHERE actor_user_id=%s AND request_id=%s',(user['id'],payload.request_id)).fetchone()
                if old:
                    if old[0]!=canonical:raise DirectoryConflict('request_id уже использован с другими данными')
                    return old[1]
            plan_id=None
            if operation=='END':
                if not plan or plan['source_kind']!='MANUAL' or plan['assignment_state']!='OBJECTS' or not plan['items']:raise DirectoryConflict('Выберите объекты планового закрепления')
                from datetime import timedelta
                return_day=payload.ends_on+timedelta(days=1)
                if plan['effective_from']!=str(return_day):raise DirectoryConflict('План начинается на следующий день после последнего дня И.О.')
                plan_for_writer={**plan,'items':[dict(i) for i in plan['items']]}
                for item in plan_for_writer['items']:
                    if item.get('initial_control_mode') is None:item.pop('initial_control_mode',None)
                saved=save(employee_id,plan_for_writer,connection=c);plan_id=saved['id']
            if personnel_local.is_local(user):
                result=c.execute('SELECT personnel_local_acting_command(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(personnel_local.sql_key(),employee_id,values.get('position_id'),values.get('starts_on'),values.get('ends_on'),values.get('reason'),payload.request_id,payload.expected_version,operation,target,plan_id,Jsonb(canonical['plan']) if canonical['plan'] is not None else None)).fetchone()[0]
            else:
                result=c.execute('SELECT personnel_acting_command(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(user['id'],user['session_id'],employee_id,values.get('position_id'),values.get('starts_on'),values.get('ends_on'),values.get('reason'),payload.request_id,payload.expected_version,operation,target,plan_id,Jsonb(canonical['plan']) if canonical['plan'] is not None else None)).fetchone()[0]
            return result
    except psycopg.Error as error:
        message=error.diag.message_primary or 'Кадровая операция не выполнена'
        if error.sqlstate=='42501':raise PermissionError(message) from None
        if error.sqlstate=='P0002':raise DirectoryNotFound(message) from None
        if error.sqlstate in ('22023','23505','23514','40001','55P03','55000'):raise DirectoryConflict(message) from None
        raise

def capabilities_on_connection(c,user):
    cfg=settings(c)
    return {'can_review':bool(cfg and cfg['creator_user_id']==user['id'] and not blockers(cfg))}


def attach_context(connection,employees):
    """Caller owns a repeatable snapshot; no writes and no substitute directory."""
    if not employees or not installed(connection):return
    cfg=settings(connection)
    if not cfg['enabled'] or not cfg['date_readers_verified']:return
    acting_installed=connection.execute("SELECT to_regclass('personnel_acting_current')").fetchone()[0] is not None
    for employee in employees:
        eid=employee['employee_id']
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT * FROM personnel_position_baselines WHERE employee_id=%s',(eid,));baseline=cur.fetchone()
            if baseline is None:raise DirectoryConflict('Не найдено исходное наблюдение должности')
            cur.execute('SELECT * FROM personnel_position_periods WHERE employee_id=%s ORDER BY known_from',(eid,));periods=cur.fetchall()
            cur.execute('SELECT * FROM personnel_position_definitions ORDER BY known_from,id');definitions=cur.fetchall()
            acting=[]
            if acting_installed:
                cur.execute('SELECT * FROM personnel_acting_current WHERE employee_id=%s ORDER BY starts_on',(eid,));acting=cur.fetchall()
        employee['personnel_context']={'baseline':baseline,'periods':periods,'definitions':definitions,'acting':acting,'legacy_history_policy':cfg['legacy_history_policy']}


def planning_context(employee_id,on_day):
    from app.repositories.production_assignments import _inputs
    from app.services.production_assignments import period_for,movement_revision
    with get_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        data=_inputs(c,employee_id);periods=[]
        for m in data['movements']:
            if m['movement_type']!='ARRIVAL':continue
            change=dict(period_kind='ARRIVAL',arrival_movement_ref=m['id'],period_revision=movement_revision(m),period_start=m['event_datetime'][:10],period_end=None,effective_from=str(on_day),source_kind='MANUAL')
            period,reason=period_for(change,data)
            if period and period['date_from']<=str(on_day) and (period['date_to'] is None or str(on_day)<=period['date_to']):periods.append({'arrival_movement_ref':m['id'],**period})
        return {'on_day':str(on_day),'periods':periods,'explicit_period_allowed':data['work_location']=='OFFICE' and data['work_schedule']=='FIVE_TWO'}


def predecessor(employee_id,on_day):
    from datetime import timedelta
    with get_connection() as c:
        if not installed(c):raise DirectoryConflict('История должностей не установлена')
        value=c.execute('SELECT personnel_position_at(%s,%s)',(employee_id,on_day-timedelta(days=1))).fetchone()[0]
        return {'on_day':str(on_day-timedelta(days=1)),**value}
