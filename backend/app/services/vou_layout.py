"""B3 layout only: ready B2 shares -> approved Personnel template cells."""
from calendar import monthrange
from datetime import date
import math
import re
from app.services.vou_settings import require_configured

BLOCKS=((14,15,61),(62,63,128),(129,130,202),(203,204,219),(220,221,243),(244,245,271))


def column(number):
    result=''
    while number:
        number,rest=divmod(number-1,26);result=chr(65+rest)+result
    return result


def validate_readback_range(address):
    m=re.fullmatch(r'B([1-9][0-9]*):AL([1-9][0-9]*)',str(address))
    if not m or not 1<=int(m[1])<=int(m[2])<=100000 or int(m[2])-int(m[1])>10000:
        raise ValueError('Invalid Personnel verification range')


def validate_layout_operation(op):
    kind=op['type']
    fields={'delete_rows':{'type','before_row','count'},'copy_row_format':{'type','source_row','target_row'},
            'autofit_rows':{'type','first_row','last_row'},'print_end':{'type','row'},
            'clear_range':{'type','address'},'set_block':{'type','address','values'},
            'fit_signatures':{'type','row'},'fit_header':{'type'}}
    if set(op)!=fields.get(kind):raise ValueError('Invalid layout operation')
    if kind=='clear_range':
        validate_readback_range(op['address'])
        if int(re.search(r'B(\d+)',op['address'])[1])<14:raise ValueError('Clear outside table')
    elif kind=='set_block':
        m=re.fullmatch(r'B([1-9][0-9]*)',str(op['address']))
        values=op['values']
        if not m or int(m[1])<14 or not isinstance(values,list) or not 1<=len(values)<=10000:
            raise ValueError('Invalid table block')
        if int(m[1])+len(values)>100000:raise ValueError('Table block too large')
        for row in values:
            if not isinstance(row,list) or len(row)!=37 or row[-1] is not None:
                raise ValueError('Table must have 37 columns and empty AL')
            for value in row:
                if value is not None and (type(value) not in (str,int,float) or
                   (type(value) is float and not math.isfinite(value))):raise ValueError('Invalid block literal')
    else:
        for key,value in op.items():
            if key=='type':continue
            if type(value) is not int or not 1<=value<=100000:raise ValueError('Invalid row bound')
        if kind=='delete_rows' and (op['before_row']<15 or op['count']>10000):raise ValueError('Invalid delete bounds')
        if kind=='copy_row_format' and min(op['source_row'],op['target_row'])<14:raise ValueError('Invalid format bounds')
        if kind=='autofit_rows' and not 14<=op['first_row']<=op['last_row']:raise ValueError('Invalid autofit bounds')
        if kind in ('print_end','fit_signatures') and op['row']<25:raise ValueError('Signatures must be in print area')


def build_plan(data,requisites,*,technical_only=False):
    settings=require_configured(requisites)
    year,month=data['year'],data['month']
    length=monthrange(year,month)[1]
    groups=data['sections']
    if [s['code'] for s in groups]!=['1','2','3','4','5','6']:raise ValueError('Unexpected six-section layout')
    if [s['code'] for s in groups[5]['subsections']]!=['6.1','6.2','6.3','6.4']:raise ValueError('Unexpected subsections')
    capacities=[max(1,len(s['rows'])) for s in groups[:5]]
    capacities.append(sum(1+max(1,len(s['rows'])) for s in groups[5]['subsections']))
    operations=[]
    # Bottom-up resizing keeps every original header/total/signature outside writes.
    for (_,first,last),wanted in reversed(list(zip(BLOCKS,capacities))):
        current=last-first+1
        if wanted>current:operations.append(dict(type='insert_rows',before_row=last+1,count=wanted-current,prototype_row=first))
        elif wanted<current:operations.append(dict(type='delete_rows',before_row=first+wanted,count=current-wanted))
    headers=[];cursor=14
    for capacity in capacities:headers.append(cursor);cursor+=1+capacity
    grand=cursor;signature=grand+11
    values=[[None]*37 for _ in range(grand-14)]
    rows=[];formulas={};expected={};section_headers={};sub_headers={}
    def put(row,col,value):values[row-14][col-2]=value
    def formula(row,col,expression):formulas[column(col)+str(row)]=expression
    def total_row(row,children):
        for col in list(range(6,6+length))+[37]:
            refs=','.join(column(col)+str(r) for r in children)
            if refs:formula(row,col,'=SUM('+refs+')')
    def fill_rows(first,source_rows,prefix):
        for offset,item in enumerate(source_rows):
            row=first+offset
            number=f'{prefix}.{offset+1}'
            put(row,2,number)
            expected['B'+str(row)]=number
            obj=item.get('subobject_name') or item.get('object_name') or ('Камеральная работа' if item['kind']=='CAMERAL' else '')
            put(row,3,obj);put(row,4,item.get('aos_description'));put(row,5,item['full_name'])
            for index in range(length):
                day=date(year,month,index+1).isoformat();cents=item['days_cents'][day]
                # Empty includes excluded DK days: never write zero/formula/marker.
                put(row,6+index,cents/100 if cents else None)
            formula(row,37,f'=SUM(F{row}:AJ{row})')
            expected['AK'+str(row)]=item['total_cents']/100
            rows.append(dict(row=row,employee_id=item['employee_id'],full_name=item['full_name'],
                category_id=item['category_id'],matrix_row_key=item.get('matrix_row_key'),days_cents=item['days_cents'],total_cents=item['total_cents']))
    for index,section in enumerate(groups):
        header=headers[index];section_headers[section['code']]=header
        put(header,2,section['code']+'.');put(header,3,section['name'])
        expected['B'+str(header)]=section['code']+'.'
        expected['AK'+str(header)]=section['total_cents']/100
        if index<5:
            fill_rows(header+1,section['rows'],section['code'])
            for col in list(range(6,6+length))+[37]:
                letter=column(col);formula(header,col,f'=SUM({letter}{header+1}:{letter}{header+capacities[index]})')
        else:
            sub_cursor=header+1;children=[]
            for sub in section['subsections']:
                sub_headers[sub['code']]=sub_cursor;children.append(sub_cursor)
                put(sub_cursor,2,sub['code']);put(sub_cursor,3,sub['name'])
                expected['AK'+str(sub_cursor)]=sub['total_cents']/100
                operations.append(dict(type='copy_row_format',source_row=14,target_row=sub_cursor))
                fill_rows(sub_cursor+1,sub['rows'],sub['code'])
                capacity=max(1,len(sub['rows']))
                for col in list(range(6,6+length))+[37]:
                    letter=column(col);formula(sub_cursor,col,f'=SUM({letter}{sub_cursor+1}:{letter}{sub_cursor+capacity})')
                sub_cursor+=1+capacity
            total_row(header,children)
    operations.append(dict(type='clear_range',address=f'B14:AL{grand}'))
    operations.append(dict(type='set_block',address='B14',values=values))
    for address,expression in formulas.items():operations.append(dict(type='set_formula',address=address,formula=expression))
    operations.extend([dict(type='set_value',address=f'B{grand}',value='ИТОГО'),
                       dict(type='set_formula',address=f'AK{grand}',formula='=SUM('+','.join('AK'+str(r) for r in headers)+')')])
    expected['AK'+str(grand)]=data['total_cents']/100
    def value(address,text):operations.append(dict(type='set_value',address=address,value=text));expected[address]=text
    for day in range(1,32):
        value(column(day+5)+'13',(date(year,month,day)-date(1899,12,30)).days if day<=length else None)
    month_name=('января','февраля','марта','апреля','мая','июня',
                'июля','августа','сентября','октября','ноября','декабря')[month-1]
    period=f'за период с 01 {month_name} {year} по {length:02d} {month_name} {year}'
    value('B8',period)
    contract_date=date.fromisoformat(settings['contract_date']).strftime('%d.%m.%Y')
    value('B9',f"к Договору № {settings['contract_number']} от {contract_date}, rev. {settings['contract_revision']}")
    value('AL4',f"к Договору № {settings['contract_number']}")
    value('B'+str(signature),'________________ /'+settings['customer_signer_name']+'/')
    value('AE'+str(signature),'________________ /'+settings['contractor_signer_name']+'/')
    if technical_only:value('B6','ТЕХНИЧЕСКАЯ ПРОВЕРКА ВОУ — НЕ ДЛЯ УЧЁТА')
    operations.append(dict(type='autofit_rows',first_row=14,last_row=grand-1))
    operations.append(dict(type='fit_signatures',row=signature))
    operations.append(dict(type='fit_header'))
    operations.append(dict(type='print_end',row=signature))
    return dict(operations=operations,rows=rows,headers=section_headers,subheaders=sub_headers,
        grand_row=grand,signature_row=signature,expected=expected,formulas=formulas,
        values=values,readback_range=f'B14:AL{grand}',date_from=f'{year:04d}-{month:02d}-01',
        date_to=f'{year:04d}-{month:02d}-{length:02d}',
        signer_names=[settings['customer_signer_name'],settings['contractor_signer_name']])
