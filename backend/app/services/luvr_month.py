from calendar import monthrange
from collections import Counter
from datetime import date
from app.repositories.luvr_month import get_month_inputs
from app.services.luvr_calendar import calculate_employee_month
from app.services.luvr_duration import calculate_duration, local_today, month_as_of


def calendar_totals(days):
    counts=Counter(d['final_code'] for d in days)
    return dict(work_days_total=(counts['FULL']*2+counts['HALF'])/2,
                travel_days_total=counts['TRAVEL'],off_shift_days_total=counts['OFF_SHIFT'],
                downtime_days_total=counts['DOWNTIME'],
                manual_changes_count=sum(d['manually_changed'] for d in days),
                sick_days_count=sum(d['is_sick'] for d in days))


def calendar_day_totals(employees, year, month):
    totals={date(year,month,day):dict(date=date(year,month,day),full_count=0,half_count=0,travel_count=0,
        off_shift_count=0,downtime_count=0,dismissed_count=0,sick_count=0,unknown_count=0,
        present_people_count=0,work_equivalent=0.0) for day in range(1,monthrange(year,month)[1]+1)}
    fields={'FULL':'full_count','HALF':'half_count','TRAVEL':'travel_count',
            'OFF_SHIFT':'off_shift_count','DOWNTIME':'downtime_count','DISMISSED':'dismissed_count'}
    for employee in employees:
        for day in employee['days']:
            total=totals[day['date']]
            field=fields.get(day['final_code'])
            if field:total[field]+=1
            if day['is_sick']:total['sick_count']+=1
            if day['final_code']=='EMPTY' and not day['is_sick'] and day['final_source_type']=='UNKNOWN':
                total['unknown_count']+=1
    for total in totals.values():
        total['present_people_count']=total['full_count']+total['half_count']
        total['work_equivalent']=(2*total['full_count']+total['half_count'])/2
    return list(totals.values())


def month_calendar(year, month, as_of_date=None):
    today=local_today()
    as_of_date=month_as_of(year,month,as_of_date,today)
    inputs=get_month_inputs(year,month)
    employees=[]
    for employee in inputs['employees']:
        row=calculate_employee_month(employee,year,month)
        row.update({key:employee.get(key) for key in ('position_name','specialty','nrs_number')})
        row['totals']=calendar_totals(row['days'])
        row['duration']=calculate_duration(employee,as_of_date)
        employees.append(row)
    return dict(year=year,month=month,days_in_month=monthrange(year,month)[1],formed=inputs['formed'],employees=employees,
                as_of_date=as_of_date,is_projection=as_of_date>today,
                day_totals=calendar_day_totals(employees,year,month))
