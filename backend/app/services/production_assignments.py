"""Assignment intervals, not a second LUVR or daily allocation calculator."""
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def movement_revision(movement):
    return revision({k: movement[k] for k in ('id', 'employee_id', 'movement_type', 'transport_type', 'event_datetime')})


def ticket_revision(ticket):
    value={k: ticket.get(k) for k in ('id', 'employee_id', 'movement_id', 'object_id', 'movement_type')}
    if ticket.get('entity_id') is not None:value['entity_id']=ticket['entity_id']
    return revision(value)


def previous_day(value):
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat()


def movement_date(movement):
    return str(movement['event_datetime'])[:10]


def canonical_movements(data):
    confirmed={t['movement_id'] for t in data['tickets'] if t['status']=='CONFIRMED' and t.get('movement_id')}
    def key(m):
        station=lambda v:' '.join((v or '').split()).casefold()
        return (m.get('employee_id',data['id']),m['movement_type'],m['event_datetime'],
                station(m.get('departure_station')),station(m.get('arrival_station')))
    authoritative={}
    for m in data['movements']:
        if m['transport_type']=='RAIL' and m['id'] in confirmed:
            authoritative.setdefault(key(m),[]).append(m)
    return [m for m in data['movements'] if not (
        m['transport_type']=='RAIL' and m['id'] not in confirmed and key(m)[3] and key(m)[4]
        and len(authoritative.get(key(m),[]))==1)]


def period_for(change, data):
    """Resolve provenance each time, so annul/restore needs no write hook."""
    movements = sorted(canonical_movements(data), key=lambda m: (m['event_datetime'], m['id']))
    tickets = {t['id']: t for t in data['tickets']}
    start, end = change['period_start'], change.get('period_end')
    if change['period_kind'] == 'ARRIVAL':
        if data['work_location'] == 'OFFICE' and data['work_schedule'] == 'FIVE_TWO':
            return None, 'EXPLICIT_PERIOD_REQUIRED'
        anchor = next((m for m in movements if m['id'] == change['arrival_movement_ref']), None)
        if not anchor:
            return None, 'ARRIVAL_MISSING'
        if anchor['movement_type'] != 'ARRIVAL' or movement_revision(anchor) != change['period_revision']:
            return None, 'ARRIVAL_CHANGED'
        if sum(movement_date(m) == start for m in movements) != 1:
            return None, 'AMBIGUOUS_MOVEMENTS'
        if anchor['transport_type'] == 'RAIL' and not any(
            t['status'] == 'CONFIRMED' and t.get('movement_id') == anchor['id'] for t in tickets.values()
        ):
            return None, 'ARRIVAL_UNCONFIRMED'
        following = [m for m in movements if (m['event_datetime'], m['id']) > (anchor['event_datetime'], anchor['id'])]
    else:
        if data['work_location'] != 'OFFICE' or data['work_schedule'] != 'FIVE_TWO':
            return None, 'EXPLICIT_PERIOD_CONFIGURATION_CHANGED'
        following = [m for m in movements if movement_date(m) >= start]
    if following:
        boundary = following[0]
        boundary_day = movement_date(boundary)
        ambiguous = sum(movement_date(m) == boundary_day for m in movements) > 1
        limit = previous_day(boundary_day) if boundary['movement_type'] == 'ARRIVAL' or ambiguous else boundary_day
        end = min(end, limit) if end else limit
    if data.get('dismissal_date'):
        limit = previous_day(data['dismissal_date'])
        end = min(end, limit) if end else limit
    if end and (end < start or change['effective_from'] > end):
        return None, 'OUTSIDE_PERIOD'
    if change['source_kind'] == 'TICKET':
        ticket = tickets.get(change['source_ticket_id'])
        if not ticket or ticket['status'] != 'CONFIRMED':
            return None, 'SOURCE_TICKET_INACTIVE'
        if ticket_revision(ticket) != change['source_revision']:
            return None, 'SOURCE_TICKET_CHANGED'
    key = f"ARRIVAL:{change['arrival_movement_ref']}:{change['period_revision']}" if change['period_kind'] == 'ARRIVAL' else f"EXPLICIT:{start}:{change['period_end']}"
    return {'key': key, 'date_from': start, 'date_to': end}, None


def project(data, date_from, date_to):
    """Return sparse effective intervals and untouched source facts. Never writes."""
    history, periods, warnings = [], {}, []
    for change in data['changes']:
        period, reason = period_for(change, data)
        history.append({**change, 'applicable': period is not None, 'inapplicable_reason': reason})
        if period:
            bucket = periods.setdefault(period['key'], {**period, 'changes': []})
            bucket['changes'].append(change)
    # Facts can start a plan in a valid arrival period even without a manual change.
    for m in canonical_movements(data):
        if data['work_location'] == 'OFFICE' and data['work_schedule'] == 'FIVE_TWO':
            continue
        if m['movement_type'] != 'ARRIVAL':
            continue
        synthetic = dict(period_kind='ARRIVAL', arrival_movement_ref=m['id'],
                         period_revision=movement_revision(m), period_start=movement_date(m),
                         period_end=None, effective_from=movement_date(m), source_kind='MANUAL')
        period, reason = period_for(synthetic, data)
        if period:
            periods.setdefault(period['key'], {**period, 'changes': []})
        else:
            warnings.append({'code': reason, 'movement_id': m['id'], 'date':movement_date(m),
                             'movement_ids':[x['id'] for x in canonical_movements(data) if movement_date(x)==movement_date(m)]})
    facts_by_date = defaultdict(list)
    for fact in data['facts']:
        facts_by_date[fact['report_date']].append(fact)
    intervals, covered = [], set()
    for period in periods.values():
        start, end = period['date_from'], period['date_to']
        events = {}
        for change in period['changes']:
            events[change['effective_from']] = {
                'basis_kind': 'ASSIGNMENT', 'basis_id': change['id'],
                'basis_revision': str(change['version']), 'assignment_state': change['assignment_state'],
                'items': change['items'],
            }
        for day, facts in facts_by_date.items():
            if day < start or (end and day > end):
                continue
            covered.update(f['id'] for f in facts)
            ordered = sorted(facts, key=lambda f: f['id'])
            events[day] = {'basis_kind': 'FACTS', 'basis_id': [f['id'] for f in ordered],
                          'basis_revision': revision(ordered), 'assignment_state': 'OBJECTS', 'items': ordered}
        dates = sorted(events)
        if not dates or dates[0] > start:
            events[start] = dict(basis_kind='UNKNOWN', basis_id=None, basis_revision=None,
                                 assignment_state='UNKNOWN', items=[])
            dates = sorted(events)
        for index, day in enumerate(dates):
            until = previous_day(dates[index + 1]) if index + 1 < len(dates) else end
            if day > date_to or (until and until < date_from):
                continue
            intervals.append({**events[day], 'period_key': period['key'],
                              'effective_from': day, 'effective_to': until,
                              'visible_from': max(day, date_from),
                              'visible_to': min(until, date_to) if until else date_to,
                              'automatic_control_mode': 'CAMERAL' if events[day]['assignment_state'] == 'NO_OBJECT' else None})
    for fact in data['facts']:
        if fact['id'] not in covered and date_from <= fact['report_date'] <= date_to:
            warnings.append({'code': 'FACT_OUTSIDE_KNOWN_PERIOD', 'fact_id': fact['id']})
    return {'employee_id': data['id'], 'history': history,
            'periods': sorted(intervals, key=lambda r: (r['effective_from'], r['period_key'])),
            'facts': [f for f in data['facts'] if date_from <= f['report_date'] <= date_to],
            'warnings': warnings,
            'availability_note': 'Intervals describe assignments only; working time must come from existing LUVR FINAL.'}
