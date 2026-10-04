"""Read-only duration of movement state; independent of monthly attendance totals."""
from bisect import bisect_right
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo
from app.services.luvr_calendar import CalendarTimeline


def local_today():
    return datetime.now(ZoneInfo('Asia/Yekaterinburg')).date()


def month_as_of(year, month, requested=None, today=None):
    today=today or local_today()
    return requested if requested is not None else min(today,date(year,month,monthrange(year,month)[1]))


def sick_days_between(periods, start, end):
    """Union inclusive ranges, including overlaps/open ends, without iterating days."""
    ranges=sorted((max(start,p['date_from']).toordinal(),min(end,p['date_to'] or end).toordinal())
                  for p in periods if p['date_from']<=end and (p['date_to'] is None or p['date_to']>=start))
    count=0;last_end=0
    for first,last in ranges:
        count+=max(0,last-max(first,last_end+1)+1)
        last_end=max(last_end,last)
    return count


def duration_indicator(duration, maximum):
    if maximum is None:return 'NONE'
    if duration>maximum:return 'EXCEEDED'
    if duration==maximum:return 'MAX_REACHED'
    return 'WARNING_50' if duration*2>=maximum else 'NORMAL'


def calculate_duration(inputs, as_of_date):
    periods=inputs['sick_periods']
    sick=any(p['date_from']<=as_of_date and (p['date_to'] is None or p['date_to']>=as_of_date) for p in periods)
    result=dict(current_state='UNKNOWN',state_since=None,as_of_date=as_of_date,
                current_duration_days=None,current_shift_days=None,current_off_shift_days=None,
                max_shift_days=inputs.get('max_shift_days'),max_off_shift_days=inputs.get('max_off_shift_days'),
                maximum_days=None,ratio=None,indicator_status='UNKNOWN',indicator_enabled=False,
                is_sick=sick,active_exception=None,active_exceptions=[],sick_periods=[],
                excluded_sick_days=0,movement_id=None,warnings=[])
    if inputs.get('dismissal_date') and inputs['dismissal_date']<=as_of_date:
        result.update(current_state='DISMISSED',indicator_status='NONE')
        return result
    if inputs.get('work_schedule')!='SHIFT':
        result.update(current_state='NOT_APPLICABLE',indicator_status='NONE')
        return result
    timeline=CalendarTimeline(inputs)
    index=bisect_right(timeline.dates,as_of_date)-1
    if index<0:return result
    movement=timeline.movements[index]
    state=timeline.states[movement['id']]
    result['warnings']=timeline.notes[movement['id']]
    if state=='UNKNOWN':return result
    start=movement['event_datetime'].date()
    excluded=sick_days_between(periods,start,as_of_date)
    duration=(as_of_date-start).days+1-excluded
    maximum=inputs.get('max_shift_days' if state=='ON_SHIFT' else 'max_off_shift_days')
    kind='SHIFT' if state=='ON_SHIFT' else 'OFF_SHIFT'
    active=sorted((p for p in inputs.get('duration_exceptions',[]) if p['exception_type']==kind
                   and p['date_from']<=as_of_date<=p['date_to']),key=lambda p:(p['date_to'],p['date_from'],p['id']),reverse=True)
    result.update(current_state=state,state_since=start,current_duration_days=duration,
                  maximum_days=maximum,ratio=duration/maximum if maximum else None,
                  indicator_status=duration_indicator(duration,maximum),indicator_enabled=maximum is not None,
                  active_exception=active[0] if active else None,active_exceptions=active,
                  excluded_sick_days=excluded,movement_id=movement['id'],
                  sick_periods=[p for p in periods if p['date_from']<=as_of_date and (p['date_to'] is None or p['date_to']>=start)])
    result['current_shift_days' if state=='ON_SHIFT' else 'current_off_shift_days']=duration
    if active:result.update(indicator_status='APPROVED_EXTENSION',indicator_enabled=True)
    if sick:result.update(indicator_status='NONE',indicator_enabled=False)
    return result
