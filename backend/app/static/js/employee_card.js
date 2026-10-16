/* Employee detail presentation. All facts and edits use existing sources. */
function employeeNextMovements(items,now,employee={}){
    const sorted=items.slice().sort((a,b)=>a.event_datetime.localeCompare(b.event_datetime)||a.id-b.id);
    const future=sorted.filter(x=>x.event_datetime>now),last=sorted.filter(x=>x.event_datetime<=now).at(-1);
    const result={ARRIVAL:undefined,DEPARTURE:undefined};
    if(last){
        const direction=last.movement_type==='ARRIVAL'?'DEPARTURE':'ARRIVAL';
        const days=last.movement_type==='ARRIVAL'?employee.max_shift_days:employee.max_off_shift_days;
        if(Number.isInteger(days)&&days>0){
            // Calendar date arithmetic only: no timezone shift or persisted movement.
            const date=new Date(last.event_datetime.slice(0,10)+'T00:00:00Z');date.setUTCDate(date.getUTCDate()+days);
            if(Number.isFinite(date.getTime())&&date.getUTCFullYear()<=9999)result[direction]={movement_type:direction,event_datetime:date.toISOString().slice(0,10),planned:true};
        }
    }
    for(const direction of ['ARRIVAL','DEPARTURE']){
        const confirmed=future.find(x=>x.movement_type===direction&&(x.confirmed_ticket_id||x.transport_type==='SELF'));
        result[direction]=confirmed||result[direction];
    }
    return result;
}
function employeeLocalNow(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Yekaterinburg',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ','T');}
function employeeCardOpen(open){
    document.getElementById('employeesPanel').classList.toggle('employee-card-open',open);
    document.querySelector('.employee-only-page-title h1').textContent=open?'Карточка сотрудника':'Сотрудники';
    if(open)window.scrollTo(0,0);
}
async function employeeCardSections(item,panel,valid,absences){
    const movements=employeeRead(`/api/employees/${item.id}/luvr/movements`);
    const add=async(title,work,className='')=>{
        const host=employeeNode('section',null,'ui-card employee-detail-section '+className);
        host.append(employeeNode('h3',title),employeeNode('p','Загрузка…','ui-muted'));panel.append(host);
        try{const content=await work();if(valid())host.replaceChildren(employeeNode('h3',title),content);}
        catch(e){if(valid())host.replaceChildren(employeeNode('h3',title),employeeNode('p',e.message,'ui-error'));}
    };
    const action=(text,run)=>{const b=employeeNode('button',text,'ui-button action-blue');b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){b.after(employeeNode('p',e.message,'ui-error'));}finally{b.disabled=false;}};return b;};
    await Promise.all([
        add('Следующий заезд / убытие',async()=>{
            const next=employeeNextMovements((await movements).items,employeeLocalNow(),item),grid=employeeNode('div',null,'employee-next-grid');
            for(const [key,label] of [['ARRIVAL','Следующий заезд'],['DEPARTURE','Следующее убытие']]){
                const event=next[key],box=employeeNode('div',null,'info-highlight');box.append(employeeNode('h4',label));
                if(!event)box.append(employeeNode('p','Нет записанного перемещения','ui-muted'));
                else{box.append(employeeNode('strong',`${luvrLocalDate(event.event_datetime)} ${event.event_datetime.slice(11,16)}`));
                    box.append(employeeChip(event.planned?'Планируемая дата':event.confirmed_ticket_id?'Подтверждено билетом':'Самостоятельно · внесено вручную',event.confirmed_ticket_id?'green':'neutral'));
                    if(event.confirmed_ticket_id)box.classList.add('employee-ticket-confirmed');
                    if(event.source_file)box.append(employeeNode('p',event.source_file,'ui-muted'));
                }grid.append(box);
            }
            return grid;
        }),
        add('Закреплённый экипаж',async()=>{
            if(!item.crew_id)return employeeNode('p','Экипаж не назначен','ui-empty');
            const crew=(await employeeRead('/api/crews')).items.find(x=>x.id===item.crew_id);
            const block=employeeFields('Данные экипажа',[['Экипаж',crew?.name||item.crew_name],['Водитель',crew?.driver_full_name],['Телефон',crew?.driver_phone],['Автомобиль',crew?.vehicle_make],['Гос. номер',crew?.vehicle_plate]]);
            if(crew)block.append(action('Перейти к экипажу',async()=>{document.getElementById('crewsNavButton').click();openCrewModal(crew);}));return block;
        }),
        add('Отсутствия',async()=>renderEmployeeAbsences(item,(await absences).items),'employee-detail-wide'),
        add('История перемещений (ЛУВР)',async()=>{
            const block=employeeNode('div',null,'employee-card-movements'),body=employeeNode('div'),error=employeeNode('p',null,'ui-error');
            error.hidden=true;error.setAttribute('role','alert');block.append(error,body);
            const history=new LuvrHistoryController(luvrHistoryRequest,state=>{if(valid())renderEmployeeLuvrHistory(body,state,['movements']);},message=>{error.textContent=message;error.hidden=false;});
            history.errorElement=error;history.open(item.id);
            history.items={movements:(await movements).items};renderEmployeeLuvrHistory(body,history,['movements']);
            const mutate=history.mutate.bind(history);
            history.mutate=async(...args)=>{const saved=await mutate(...args);if(saved&&valid())await renderEmployeeProfile();return saved;};
            return block;
        },'employee-detail-wide'),
        add(`Производственная матрица — ${item.full_name}`,async()=>{
            const block=document.getElementById('productionMatrixPage').cloneNode(true);
            block.removeAttribute('id');block.hidden=false;block.classList.add('employee-personal-matrix');
            for(const node of block.querySelectorAll('[id]')){node.dataset.pmId=node.id;node.removeAttribute('id');}
            block.querySelector('.pm-toolbar h2').remove();
            const find=id=>block.querySelector(`[data-pm-id="${id}"]`);
            // Never clone rendered employees or selections from the full matrix.
            for(const id of ['pmTable','pmDetails','pmStatus','pmError'])find(id).replaceChildren();
            find('pmDetails').hidden=true;find('pmError').hidden=true;
            find('pmOpenLuvr').hidden=true;find('pmOpenReports').hidden=true;
            const full=action('Открыть полную матрицу',async()=>{
                document.getElementById('productionMatrixNavButton').click();
                document.getElementById('pmMonth').value=find('pmMonth').value;
                await document.getElementById('pmMonth').onchange();
            });block.querySelector('.pm-toolbar').append(full);
            initProductionMatrix({root:block,employeeId:item.id,month:employeeWorkspace.matrixMonth||employeeToday().slice(0,7),
                onMonthChange:month=>{employeeWorkspace.matrixMonth=month;}});
            return block;
        },'employee-detail-wide')
    ]);
}
async function saveEmployeeData(id,body){
    const r=await fetch(id?`/api/employees/${id}`:'/api/employees',{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await r.json();if(!r.ok)throw Error(data.message||'Не удалось сохранить сотрудника');return data;
}
async function editEmployeeCard(item){
    employeeWorkspace.editingId=item.id;
    const card=document.getElementById('employeeProfile'),epoch=++employeeWorkspace.epoch;
    card.replaceChildren(employeeNode('p','Загрузка формы…','ui-muted'));
    try{
        const [positions,crews]=await Promise.all([employeeRead('/api/positions'),employeeRead('/api/crews')]);
        if(epoch!==employeeWorkspace.epoch)return;
        const form=employeeNode('form',null,'employee-inline-editor'),grid=employeeNode('div',null,'employee-editor-grid'),fields={};
        form.append(employeeNode('h2','Карточка сотрудника'),grid);
        function field(key,label,value,type='text',options=null){
            const wrap=employeeNode('label',label),input=employeeNode(options?'select':'input',null,'ui-input');input.name=key;
            if(options)for(const [v,t] of options){const option=employeeNode('option',t);option.value=v;input.append(option);}else input.type=type;
            input.value=value??'';wrap.append(input);grid.append(wrap);fields[key]=input;return input;
        }
        field('full_name','ФИО',item.full_name).required=true;
        const position=field('position_id','Должность',item.position_id,'text',[['','Не указана'],...positions.items.map(p=>[p.id,p.name])]);
        field('phone','Телефон',item.phone);field('email','Email',item.email,'email').maxLength=254;
        field('nrs_number','№ НРС',item.nrs_number);
        field('crew_id','Экипаж',item.crew_id,'text',[['','Не назначен'],...crews.items.map(c=>[c.id,c.name||c.driver_full_name])]);
        const location=field('work_location','Место работы (из должности)',item.work_location,'text',[['','Не указано'],['OBJECT','Объект'],['OFFICE','Офис']]);
        const schedule=field('work_schedule','График (из должности)',item.work_schedule,'text',[['','Не указан'],['SHIFT','Вахта'],['FIVE_TWO','5/2']]);
        field('specialty','Специальность (из должности)',item.specialty).readOnly=true;
        for(const [key,label] of [['max_shift_days','Максимальная вахта, дней'],['max_off_shift_days','Максимальная МВ, дней']]){const input=field(key,label,item[key],'number');input.min=1;input.max=2147483647;input.step=1;}
        field('dismissal_date','Дата увольнения',item.dismissal_date,'date');
        const sync=()=>{const p=positions.items.find(p=>String(p.id)===position.value);location.value=p?.work_location||'';schedule.value=p?.work_schedule||'';fields.specialty.value=p?.specialty||'';position.setCustomValidity('');};position.onchange=sync;sync();
        const filterPositions=()=>{
            if(location.value==='OBJECT')schedule.value='SHIFT';
            const selected=position.value;position.replaceChildren();
            const empty=employeeNode('option','Выберите подходящую должность');empty.value='';position.append(empty);
            for(const p of positions.items.filter(p=>(!location.value||p.work_location===location.value)&&(!schedule.value||p.work_schedule===schedule.value))){const option=employeeNode('option',p.name);option.value=p.id;position.append(option);}
            position.value=selected;if(!position.value){position.value='';fields.specialty.value='';position.setCustomValidity('Выберите существующую должность с указанными местом работы и графиком');}else position.setCustomValidity('');
        };location.onchange=schedule.onchange=filterPositions;
        form.append(employeeNode('p','Место работы и график изменяются выбором должности с нужными параметрами. Параметры других сотрудников не меняются.','ui-muted'));
        const actions=employeeNode('div',null,'employee-profile-actions'),save=employeeNode('button','Сохранить','ui-button ui-button-primary'),cancel=employeeNode('button','Отмена','ui-button'),error=employeeNode('p',null,'ui-error');error.hidden=true;
        save.type='submit';cancel.type='button';cancel.onclick=()=>renderEmployeeProfile();actions.append(save,cancel);form.append(actions,error);
        form.onsubmit=async e=>{e.preventDefault();if(!form.reportValidity())return;const body={};
            for(const key of ['full_name','phone','email','nrs_number','dismissal_date'])body[key]=fields[key].value.trim()||null;
            if(!body.full_name){fields.full_name.setCustomValidity('Введите ФИО');fields.full_name.reportValidity();fields.full_name.oninput=()=>fields.full_name.setCustomValidity('');return;}
            for(const key of ['position_id','crew_id','max_shift_days','max_off_shift_days'])body[key]=fields[key].value?Number(fields[key].value):null;
            save.disabled=cancel.disabled=true;error.hidden=true;
            try{const result=await saveEmployeeData(item.id,body);employeeWorkspace.editingId=null;document.dispatchEvent(new CustomEvent('employee-saved',{detail:{id:result.id}}));await loadEmployees();}
            catch(err){if(epoch===employeeWorkspace.epoch){error.textContent=err.message;error.hidden=false;save.disabled=cancel.disabled=false;}}
        };
        card.replaceChildren(form);
    }catch(err){if(epoch===employeeWorkspace.epoch){card.replaceChildren(employeeNode('p',err.message,'ui-error'));const back=employeeNode('button','Назад','ui-button');back.onclick=()=>renderEmployeeProfile();card.append(back);}}
}
if(typeof module!=='undefined')module.exports={employeeNextMovements};
