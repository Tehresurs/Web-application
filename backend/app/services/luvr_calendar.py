"""Pure calendar projection of confirmed facts. No database writes, clock or AI."""
from bisect import bisect_right
from calendar import monthrange
from datetime import date, time
from itertools import groupby

DISPLAY={'FULL':'1','HALF':'0,5','TRAVEL':'Д','OFF_SHIFT':'МВ','DOWNTIME':'П','DISMISSED':'Уволен','EMPTY':''}
MESSAGES={
    'INVALID_WORK_CONFIGURATION':'Некорректное сочетание места работы и графика 5/2.',
    'MOVEMENT_SEQUENCE_WARNING':'Подряд записаны одинаковые события. Проверьте историю перемещений.',
    'MULTIPLE_MOVEMENTS_DAY':'В этот день несколько событий: значение дня требует проверки.',
    'SIMULTANEOUS_MOVEMENTS':'Заезд и выезд имеют одинаковое время; последующее состояние неизвестно.',
    'RAIL_SOURCE_MISSING':'У ЖД-перемещения нет подтверждённого билета: дни поездки определить нельзя.',
    'RAIL_SOURCE_CONFLICT':'Данные ЖД-билета противоречат событию; требуется проверка.',
    'RAIL_TRAVEL_CONFLICT':'День поездки пересекается с другим событием, поездкой или состоянием на вахте.',
    'SICK_OVERRIDE_CONFLICT':'На день болезни есть ручная корректировка. Итог пустой, корректировка сохранена.',
    'DISMISSAL_OVERRIDE_CONFLICT':'Есть ручная корректировка на дату увольнения или позже; она сохранена, но не применяется.',
    'DISMISSAL_SICK_CONFLICT':'Дата увольнения совпадает с болезнью; отображается увольнение.',
}


def event_code(movement):
    clock=movement['event_datetime'].time()
    if movement['movement_type']=='ARRIVAL':
        return 'FULL' if clock<time(8) else 'HALF' if clock<time(13) else 'TRAVEL'
    return 'TRAVEL' if clock<time(13) else 'HALF' if clock<time(20) else 'FULL'


def warning(code, ids=()):
    return {'code':code,'message':MESSAGES[code],'movement_ids':sorted(set(ids))}


class CalendarTimeline:
    def __init__(self, inputs):
        self.inputs=inputs
        # Imported history may already contain the same rail event before its
        # ticket is confirmed. Prefer its confirmed counterpart without deleting
        # history or merging distinct movements/trips.
        def rail_event_key(m):
            station=lambda value:' '.join((value or '').split()).casefold()
            return (m.get('employee_id',inputs.get('employee_id')),m['movement_type'],
                    m['event_datetime'],station(m.get('departure_station') or m.get('ticket_origin')),
                    station(m.get('arrival_station') or m.get('ticket_destination')))
        confirmed={}
        for m in inputs['movements']:
            if m['transport_type']=='RAIL' and m.get('ticket_id'):
                key=rail_event_key(m)
                confirmed.setdefault(key,[]).append(m)
        movements=[]
        for m in inputs['movements']:
            key=rail_event_key(m)
            if (m['transport_type']=='RAIL' and not m.get('ticket_id')
                    and key[3] and key[4] and len(confirmed.get(key,[]))==1):
                continue
            movements.append(m)
        self.movements=sorted(movements,key=lambda m:(m['event_datetime'],m['id']))
        self.dates=[m['event_datetime'].date() for m in self.movements]
        self.states={};self.notes={m['id']:[] for m in self.movements};self.trips=[]
        previous=None
        for stamp,group in groupby(self.movements,key=lambda m:m['event_datetime']):
            events=list(group);types={m['movement_type'] for m in events}
            state='UNKNOWN' if len(types)>1 else 'ON_SHIFT' if 'ARRIVAL' in types else 'OFF_SHIFT'
            for movement in events:
                mid=movement['id'];self.states[mid]=state
                if previous and previous['movement_type']==movement['movement_type']:
                    self.notes[mid].append(warning('MOVEMENT_SEQUENCE_WARNING',[previous['id'],mid]))
                if len(types)>1:self.notes[mid].append(warning('SIMULTANEOUS_MOVEMENTS',[m['id'] for m in events]))
                previous=movement
        for m in self.movements:
            if m['transport_type']!='RAIL' or m['movement_type'] not in ('ARRIVAL','DEPARTURE'):continue
            if not m.get('ticket_id'):
                self.notes[m['id']].append(warning('RAIL_SOURCE_MISSING',[m['id']]))
                continue
            start,end=m.get('ticket_departure'),m.get('ticket_arrival')
            station=lambda value:' '.join((value or '').split()).casefold()
            if m['movement_type']=='DEPARTURE':
                if (not start or not end or start!=m['event_datetime'] or end<start
                        or station(m.get('ticket_origin'))!='салым'
                        or not station(m.get('ticket_destination')) or station(m.get('ticket_destination'))=='салым'):
                    self.notes[m['id']].append(warning('RAIL_SOURCE_CONFLICT',[m['id']]))
                    continue
                self.trips.append((start.date(),end.date(),m))
                continue
            if (not start or not end or end!=m['event_datetime'] or end<start
                    or station(m.get('ticket_destination'))!='салым'
                    or not station(m.get('ticket_origin')) or station(m.get('ticket_origin'))=='салым'):
                self.notes[m['id']].append(warning('RAIL_SOURCE_CONFLICT',[m['id']]))
                continue
            self.trips.append((start.date(),end.date(),m))
        self.overrides={o['work_date']:o for o in inputs['overrides']}

    def day(self, target):
        mode=self.inputs.get('work_schedule')
        calculated=mode=='SHIFT'
        index=bisect_right(self.dates,target)-1
        latest=self.movements[index] if index>=0 else None
        events=[m for m in self.movements if m['event_datetime'].date()==target] if calculated else []
        trips=[m for start,end,m in self.trips
               if (start<target<=end if m['movement_type']=='DEPARTURE' else start<=target<end)] if calculated else []
        state=self.states[latest['id']] if calculated and latest else 'UNKNOWN'
        auto='EMPTY';source='UNKNOWN';status='UNKNOWN';ids=[];notes=[]
        if mode=='FIVE_TWO':
            if self.inputs.get('work_location')=='OFFICE':
                auto='FULL' if target.weekday()<5 else 'EMPTY'
                source='WEEKDAY' if target.weekday()<5 else 'WEEKEND'
                status='CALCULATED'
            else:
                status='NEEDS_REVIEW'
                notes.append(warning('INVALID_WORK_CONFIGURATION'))
        if calculated:
            if latest:
                ids=[latest['id']];notes.extend(self.notes[latest['id']])
                if state!='UNKNOWN':auto='FULL' if state=='ON_SHIFT' else 'OFF_SHIFT';source='STATE';status='CALCULATED'
            if events:
                ids=[m['id'] for m in events];notes=[n for m in events for n in self.notes[m['id']]]
                if len(events)==1:
                    auto=event_code(events[0]);source=events[0]['movement_type'];status='CALCULATED'
                else:
                    auto='EMPTY';source='UNKNOWN';status='NEEDS_REVIEW';notes.append(warning('MULTIPLE_MOVEMENTS_DAY',ids))
            if trips:
                ids=sorted(set(ids+[m['id'] for m in trips]))
                if events or len(trips)>1 or state=='ON_SHIFT':
                    auto='EMPTY';source='UNKNOWN';status='NEEDS_REVIEW';notes.append(warning('RAIL_TRAVEL_CONFLICT',ids))
                else:
                    # Clock thresholds apply to site movements only. Every other
                    # date covered by the ticket is travel, in either direction.
                    # Same-date trips retain the movement event's priority above.
                    auto='TRAVEL'
                    source='RAIL_TRAVEL';status='CALCULATED'
            if events and any(n['code']=='RAIL_SOURCE_CONFLICT' for n in notes):
                auto='EMPTY';source='UNKNOWN';status='NEEDS_REVIEW'
        sick=any(s['date_from']<=target and (s['date_to'] is None or target<=s['date_to']) for s in self.inputs['sick_periods'])
        override=self.overrides.get(target)
        dismissal=self.inputs.get('dismissal_date')
        # Dismissal is a permanent bound; sickness never changes movement state.
        if dismissal and target>=dismissal:
            auto='DISMISSED' if target==dismissal else 'EMPTY';source='DISMISSAL';status='CALCULATED'
        final=override['value'] if override else auto
        final_source='OVERRIDE' if override else source
        if sick:
            final='EMPTY';final_source='SICK'
            if override:notes.append(warning('SICK_OVERRIDE_CONFLICT'))
        if dismissal and target>=dismissal:
            final=auto;final_source='DISMISSAL'
            if override:notes.append(warning('DISMISSAL_OVERRIDE_CONFLICT'))
            if sick and target==dismissal:notes.append(warning('DISMISSAL_SICK_CONFLICT'))
        return {'date':target,'auto_code':auto,'auto_display':DISPLAY[auto],
                'final_code':final,'final_display':DISPLAY[final],'manually_changed':override is not None,
                'is_sick':sick,'movement_ids':ids,'warnings':notes,'state':state,'calculation_status':status,
                'source_type':source,'final_source_type':final_source,
                'override_id':override['id'] if override else None,'override_code':override['value'] if override else None,
                'override_comment':override.get('comment') if override else None}


def calculate_employee_day(inputs, target):
    return CalendarTimeline(inputs).day(target)


def calculate_employee_month(inputs, year, month):
    timeline=CalendarTimeline(inputs)
    mode='SHIFT' if inputs.get('work_schedule')=='SHIFT' else ('FIVE_TWO' if inputs.get('work_location')=='OFFICE' else 'CONFIGURATION_ERROR') if inputs.get('work_schedule')=='FIVE_TWO' else 'UNKNOWN_WORK_SCHEDULE'
    return {key:inputs.get(key) for key in ('employee_id','full_name','work_location','work_schedule','is_archived','dismissal_date')} | {
        'year':year,'month':month,'mode':mode,
        'days':[timeline.day(date(year,month,day)) for day in range(1,monthrange(year,month)[1]+1)]}
