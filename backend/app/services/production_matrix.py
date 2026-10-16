from calendar import monthrange
from datetime import date
from app.repositories.production_matrix import get_inputs
from app.services.luvr_calendar import calculate_employee_month
from app.services.production_assignments import project
from app.services.production_matrix_overrides import resolve

RANK = {'OK':0,'WARNING':1,'CONFLICT':2}


def distribute(cents, count):
    if not count:
        return []
    each = cents // count
    return [each] * (count-1) + [cents-each*(count-1)]


def stable_order(item):
    return tuple(item.get(k) or 0 for k in ('object_id','subobject_id','po_id','subcontractor_id','id'))


def _contains(interval, day):
    return interval['effective_from'] <= day and (interval['effective_to'] is None or day <= interval['effective_to'])


def employee_matrix(employee, names, year, month):
    first, last = date(year,month,1).isoformat(),date(year,month,monthrange(year,month)[1]).isoformat()
    calendar = calculate_employee_month(employee,year,month)
    production, overrides = employee['production'],employee['matrix_overrides']
    cameral_position=employee.get('requires_daily_report') is False
    assignments = project(production,first,last)
    effective = resolve(production,overrides,first,last)
    approved_po_absence=set(employee.get('approved_po_absence_fact_ids',[]))
    facts = {}
    for fact in production['facts']:
        facts.setdefault(fact['report_date'],[]).append(fact)
    rows, checks = {}, []
    totals = dict(available_cents=0,object_cents=0,cameral_cents=0,distributed_cents=0,
                  working_days=0,warning_days=0,conflict_days=0)
    def name(table, value):
        return names[table].get(value) if value is not None else None
    for luvr in calendar['days']:
        day = luvr['date'].isoformat()
        available = {'FULL':100,'HALF':50}.get(luvr['final_code'],0)
        calendar_unknown=(luvr['final_code']=='EMPTY' and luvr['calculation_status']=='UNKNOWN'
                          and luvr['final_source_type']=='UNKNOWN')
        messages = []
        status = 'OK'
        def issue(code, level):
            nonlocal status
            if code not in messages: messages.append(code)
            if RANK[level] > RANK[status]: status = level
        if luvr['calculation_status'] == 'NEEDS_REVIEW':
            issue('LUVR_NEEDS_REVIEW','CONFLICT')
        elif luvr['calculation_status'] == 'UNKNOWN' and (luvr['final_code']!='EMPTY' or (day in facts and not cameral_position)):
            # An empty calendar and no factual entry agree at zero time.
            # Still flag a factual entry whose available time is unknown.
            issue('LUVR_UNKNOWN','WARNING')
        elif luvr['warnings']:
            issue('LUVR_WARNINGS','WARNING')
        periods = [] if cameral_position else [p for p in assignments['periods'] if _contains(p,day)]
        if len(periods)>1:
            issue('OVERLAPPING_ASSIGNMENT_PERIODS','CONFLICT')
        period = periods[0] if len(periods)==1 else None
        source = 'FACT' if day in facts and not cameral_position else 'PLAN'
        items = sorted(facts[day],key=stable_order) if source=='FACT' else []
        cameral = False
        automatic_cameral = False
        if cameral_position:
            # Position policy takes precedence over uploaded reports and object
            # assignments. Source facts stay stored but do not enter this matrix.
            cameral = automatic_cameral = available>0
        elif source=='FACT':
            # LUVR is the time budget. A received report remains FACT even
            # when its share is zero; receipt alone is not an allocation conflict.
            if not period or period['basis_kind']!='FACTS':
                issue('FACT_OUTSIDE_KNOWN_PERIOD','WARNING' if calendar_unknown else 'CONFLICT')
        elif available:
            if period and period['assignment_state']=='OBJECTS':
                items = sorted(period['items'],key=stable_order)
            elif period and period['assignment_state']=='NO_OBJECT':
                cameral = True
            elif employee.get('requires_daily_report') is False and len(periods)<=1:
                # Fallback only: never replace a valid object plan inherited from
                # facts or an explicit assignment, or hide overlapping periods.
                cameral = automatic_cameral = True
            else:
                issue('ASSIGNMENT_UNKNOWN','WARNING')
        shares = distribute(available,len(items)) if len(periods)<=1 else [0]*len(items)
        entries = []
        for item, share in zip(items,shares):
            fact_basis = source=='FACT' or (period and period['basis_kind']=='FACTS')
            matched = [r for r in effective['intervals'] if r.get('scope')==source and _contains(r,day)
                       and (r.get('fact_id')==item['id'] if fact_basis else r.get('assignment_item_id')==item['id'])
                       and (not period or r['period_key']==period['period_key'] or (source=='FACT' and r['period_key']=='FACT:'+str(item['id'])))]
            overlay = matched[0] if len(matched)==1 else None
            category = overlay['category_id'] if overlay else item.get('category_id') if fact_basis else item.get('initial_category_id')
            mode = overlay['control_mode'] if overlay else None if fact_basis else item.get('initial_control_mode')
            # An approved absence belongs to the confirmed source and also to
            # plans inherited from that source, never to arbitrary empty plans.
            po_missing=item.get('po_id') is None and not (fact_basis and item['id'] in approved_po_absence)
            if mode is None:
                mode=employee.get('default_control_mode') or 'INSPECTION'
            if available and (po_missing or category is None or mode is None):
                issue('ASSIGNMENT_INCOMPLETE','WARNING')
            targets = None
            if overlay and overlay.get('editable'):
                targets = {k:overlay[k] for k in ('scope','period_key','basis_revision','fact_id','assignment_item_id')}
                targets['effective_from'] = day
                targets['fields'] = {}
                for field in ('CATEGORY','CONTROL_MODE'):
                    existing = next((o for o in overrides if o['field_name']==field and str(o['effective_from'])==day
                        and o['scope']==source and o['period_key']==targets['period_key'] and o['basis_revision']==targets['basis_revision']
                        and (o['fact_id']==item['id'] if fact_basis else o['assignment_item_ref']==item['id'])),None)
                    targets['fields'][field] = {'version':existing['version'] if existing else 0,
                                                'override_id':existing['id'] if existing else None}
            entry = dict(kind='OBJECT',source=source,object_id=item['object_id'],object_name=name('construction_objects',item['object_id']),
                subobject_id=item.get('subobject_id'),subobject_name=name('construction_subobjects',item.get('subobject_id')),
                po_id=item.get('po_id'),po_name=name('po_types',item.get('po_id')),
                subcontractor_id=item.get('subcontractor_id'),subcontractor_name=name('po_types',item.get('subcontractor_id')),
                category_id=category,category_name=name('object_categories',category),control_mode=mode,
                allowed_control_modes=employee.get('allowed_control_modes',['INSPECTION','OPERATIONAL']),
                share_cents=share,share=share/100,share_text=f'{share/100:.2f}',
                source_fact_id=item['id'] if fact_basis else None,assignment_item_id=None if fact_basis else item['id'],
                source_file=item.get('source_file'),source_document_url=None,
                report_required=bool(employee.get('requires_daily_report')) and available>0,
                report_received=source=='FACT',edit_target=targets,
                applied_overrides=overlay.get('applied_overrides',{}) if overlay else {})
            if 'entities' in names:
                from app.repositories.construction_identity import presentation
                key=('entity',item['entity_id']) if item.get('entity_id') is not None else ('subobject',item['subobject_id']) if item.get('subobject_id') is not None else ('object',item['object_id'])
                entry.update(presentation(names['entities'][key]))
            entries.append(entry)
        if cameral:
            entries.append(dict(kind='CAMERAL',source='PLAN',object_id=None,object_name=None,category_id=None,
                control_mode='CAMERAL',share_cents=available,share=available/100,share_text=f'{available/100:.2f}',
                source_fact_id=None,assignment_item_id=None,report_required=False,report_received=False,edit_target=None))
        object_cents = sum(e['share_cents'] for e in entries if e['kind']=='OBJECT')
        cameral_cents = sum(e['share_cents'] for e in entries if e['kind']=='CAMERAL')
        distributed = object_cents+cameral_cents
        if distributed>available: issue('OVER_ALLOCATION','CONFLICT')
        elif distributed<available: issue('UNALLOCATED_WORK_TIME','WARNING')
        occurrences = {}
        for entry in entries:
            entry.update(date=day,employee_id=employee['employee_id'],employee_name=employee['full_name'],
                position_name=employee.get('position_name'),status=status,warnings=list(messages),
                luvr_final_code=luvr['final_code'],available_cents=available,
                period_key=period['period_key'] if period else None,
                basis_kind=period['basis_kind'] if period else 'FACTS',basis_id=period['basis_id'] if period else entry['source_fact_id'])
            if automatic_cameral:
                entry.update(basis_kind='POSITION_RULE',basis_id=employee.get('position_id'))
            identity = (entry['kind'],entry.get('object_id'),entry.get('subobject_id'),
                        entry.get('po_id'),entry.get('subcontractor_id'))
            if entry.get('entity_id') is not None:
                identity=(entry['kind'],'entity',entry['entity_id'],entry.get('po_id'),entry.get('subcontractor_id'))
            # Group display rows across dates, not source records. Preserve a
            # separate lane for simultaneous equal identities: never overwrite
            # a fact/correction target or sum away its provenance.
            occurrence = occurrences.get(identity,0)
            occurrences[identity] = occurrence+1
            key = ':'.join(str(value) for value in (employee['employee_id'],*identity,occurrence))
            row = rows.setdefault(key,dict(row_key=key,kind=entry['kind'],object_id=entry['object_id'],
                object_name=entry['object_name'],source=source,cells={},total_cents=0))
            row['cells'][day] = entry
            if entry.get('entity_id') is not None:
                row.update({k:entry[k] for k in ('entity_id','parent_entity_id','current_hierarchy','subobject_name')})
            if row['source']!=source:row['source']='MIXED'
            row['total_cents'] += entry['share_cents']
        checks.append(dict(date=day,object_cents=object_cents,cameral_cents=cameral_cents,
            distributed_cents=distributed,available_cents=available,status=status,warnings=messages))
        for key,value in [('available_cents',available),('object_cents',object_cents),('cameral_cents',cameral_cents),('distributed_cents',distributed)]:
            totals[key]+=value
        totals['working_days']+=int(available>0)
        totals['warning_days']+=int(status=='WARNING')
        totals['conflict_days']+=int(status=='CONFLICT')
    return dict(employee_id=employee['employee_id'],full_name=employee['full_name'],position_id=employee.get('position_id'),
                position_name=employee.get('position_name'),requires_daily_report=employee.get('requires_daily_report'),
                work_location=employee.get('work_location'),work_schedule=employee.get('work_schedule'),
                luvr_days=calendar['days'],rows=list(rows.values()),checks=checks,totals=totals,
                source_warnings=[] if cameral_position else assignments['warnings'])


def calculate_month(year,month,employee_id=None):
    inputs = get_inputs(year,month,employee_id)
    employees = [employee_matrix(e,inputs['names'],year,month) for e in inputs['employees']]
    totals = {k:sum(e['totals'][k] for e in employees) for k in
              ('available_cents','object_cents','cameral_cents','distributed_cents','working_days','warning_days','conflict_days')}
    day_totals = []
    for index in range(monthrange(year,month)[1]):
        checks = [e['checks'][index] for e in employees]
        day_totals.append(dict(date=date(year,month,index+1).isoformat(),
            **{key:sum(c[key] for c in checks) for key in ('object_cents','cameral_cents','distributed_cents','available_cents')},
            status=max((c['status'] for c in checks),key=lambda s:RANK[s],default='OK'),
            warnings=sorted({w for c in checks for w in c['warnings']})))
    return dict(year=year,month=month,formed=inputs['formed'],employees=employees,totals=totals,
                day_totals=day_totals,
                time_unit='hundredth_of_workday',warnings=[] if inputs['formed'] else ['LUVR_MONTH_NOT_FORMED'])
