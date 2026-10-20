"""Sparse category/mode overlays on stage 3A intervals; no work-time calculation."""
from datetime import date, timedelta
from app.services.production_assignments import project, revision


def next_day(value):
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def editable_periods(data):
    source=project(data, '0001-01-02', '9999-12-30')
    periods=list(source['periods'])
    # A saved fact remains editable even when movement history cannot establish
    # its assignment period. This does not establish a plan or allocate time.
    for item in data['facts']:
        covered=any(p['assignment_state']=='OBJECTS' and p['basis_kind']=='FACTS'
                    and p['effective_from']<=item['report_date']
                    and (p['effective_to'] is None or item['report_date']<=p['effective_to'])
                    and any(i['id']==item['id'] for i in p['items']) for p in periods)
        if not covered:
            periods.append(dict(period_key='FACT:'+str(item['id']),basis_revision=revision(item),
                                assignment_state='OBJECTS',basis_kind='FACTS',
                                effective_from=item['report_date'],effective_to=item['report_date'],items=[item]))
    return source,periods


def control_identity(item):
    ref=('entity',item['entity_id']) if item.get('entity_id') is not None else ('object',item.get('object_id'),item.get('subobject_id'))
    return (ref,item.get('po_id'),item.get('subcontractor_id'))


def match_source(periods, change):
    # Keep corrections made while the fact lacked a trusted arrival period.
    # Restoring that period must not discard an already chosen mode/category.
    if change['scope']=='FACT' and change.get('fact_id') is not None and change['period_key']=='FACT:'+str(change['fact_id']):
        for period in periods:
            if period['basis_kind']!='FACTS' or period['assignment_state']!='OBJECTS':continue
            item=next((i for i in period['items'] if i['id']==change['fact_id']),None)
            if item and str(change['effective_from'])==item['report_date'] and change['basis_revision']==revision(item):
                return period,item
        return None
    for period in periods:
        if (period['period_key'] != change['period_key'] or (change['scope']=='PLAN' and period['basis_revision'] != change['basis_revision'])
                or period['assignment_state'] != 'OBJECTS'):
            continue
        day = str(change['effective_from'])
        if day < period['effective_from'] or (period['effective_to'] and day > period['effective_to']):
            continue
        if change.get('fact_id') is not None:
            if period['basis_kind'] != 'FACTS':
                continue
            item = next((i for i in period['items'] if i['id'] == change['fact_id']), None)
            if not item:
                continue
            if change['scope'] == 'FACT' and day != item['report_date']:
                continue
            if change['scope'] == 'FACT' and change['basis_revision'] != revision(item):
                continue
            if change['scope'] == 'PLAN' and day <= item['report_date']:
                continue
        else:
            if change['scope'] != 'PLAN' or period['basis_kind'] != 'ASSIGNMENT':
                continue
            item = next((i for i in period['items'] if i['id'] == change['assignment_item_ref']), None)
        if item and (item.get('object_id') is not None or item.get('entity_id') is not None):
            return period, item
    return None


def resolve(data, overrides, date_from, date_to):
    # Full source intervals are needed to validate changes before the requested month.
    source,periods = editable_periods(data)
    history, applicable = [], []
    mode_changes=[]
    for change in overrides:
        match = match_source(periods, change)
        active = not change['is_deleted'] and match is not None
        history.append({**change, 'applicable': active,
                        'inapplicable_reason': 'DELETED' if change['is_deleted'] else None if match else 'SOURCE_OR_PERIOD_CHANGED'})
        if active:
            applicable.append(change)
            if change['field_name']=='CONTROL_MODE':mode_changes.append((change,match[1]))
    intervals = []
    for period in periods:
        start = max(period['effective_from'], date_from)
        end = min(period['effective_to'] or date_to, date_to)
        if start > end:
            continue
        if period['assignment_state'] != 'OBJECTS':
            intervals.append({'period_key': period['period_key'], 'effective_from': start, 'effective_to': end,
                              'assignment_state': period['assignment_state'], 'category_id': None,
                              'control_mode': 'CAMERAL' if period['assignment_state'] == 'NO_OBJECT' else None,
                              'editable': False})
            continue
        for item in period['items']:
            fact = period['basis_kind'] == 'FACTS'
            modes = ['FACT', 'PLAN'] if fact else ['PLAN']
            for scope in modes:
                basis_revision = revision(item) if scope == 'FACT' else period['basis_revision']
                left = max(start, item['report_date'] if scope == 'FACT' else next_day(item['report_date']) if fact else start)
                right = min(end, item['report_date']) if scope == 'FACT' else end
                if left > right:
                    continue
                candidates = [o for o in applicable if o['scope'] == scope
                              and (o['period_key'] == period['period_key'] or (scope=='FACT' and o['period_key']=='FACT:'+str(item['id']))) and o['basis_revision'] == basis_revision
                              and (o['fact_id'] == item['id'] if fact else o['assignment_item_ref'] == item['id'])]
                inherited_modes=[o for o,origin in mode_changes if control_identity(origin)==control_identity(item)]
                boundaries = sorted({left} | {str(o['effective_from']) for o in candidates+inherited_modes if left < str(o['effective_from']) <= right})
                for index, day in enumerate(boundaries):
                    until = (date.fromisoformat(boundaries[index+1]) - timedelta(days=1)).isoformat() if index+1 < len(boundaries) else right
                    category = item.get('category_id') if fact else item.get('initial_category_id')
                    mode = None if fact else item.get('initial_control_mode')
                    po = item.get('po_id')
                    applied = {}
                    for field in ('CATEGORY','CONTROL_MODE','PO'):
                        options = [o for o in candidates if o['field_name'] == field and str(o['effective_from']) <= day]
                        if options:
                            chosen = max(options, key=lambda o: str(o['effective_from']))
                            if field == 'CATEGORY': category = chosen['category_id']
                            elif field == 'PO': po = chosen['po_id']
                            else: mode = chosen['control_mode']
                            applied[field] = chosen['id']
                    prior_modes=[o for o in inherited_modes if str(o['effective_from'])<=day]
                    if prior_modes:
                        chosen=max(prior_modes,key=lambda o:(str(o['effective_from']),o['id']))
                        mode=chosen['control_mode'];applied['CONTROL_MODE']=chosen['id']
                    intervals.append({'period_key': period['period_key'], 'basis_revision': basis_revision,
                                      'scope': scope, 'fact_id': item['id'] if fact else None,
                                      'assignment_item_id': None if fact else item['id'], 'object_id': item['object_id'],
                                      'effective_from': day, 'effective_to': until, 'category_id': category, 'po_id': po,
                                      'control_mode': mode, 'applied_overrides': applied, 'editable': True})
    return {'employee_id': data['id'], 'history': history, 'intervals': intervals, 'warnings': source['warnings']}
