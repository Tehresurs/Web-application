/* Presentation only; mutations remain in the existing employee/history forms. */
function employeeToday(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Yekaterinburg'}).format(new Date());}
function employeeStatus(item,today=employeeToday()){return item.dismissal_date&&item.dismissal_date<=today?'Уволен':'Работает';}
function filterEmployeeWorkspace(items,query,status,place,schedule,today=employeeToday()){
    const q=query.trim().toLocaleLowerCase('ru');
    return items.filter(e=>(!q||[e.full_name,e.position_name,e.phone,e.nrs_number,e.crew_name].some(v=>String(v||'').toLocaleLowerCase('ru').includes(q)))&&(!status||employeeStatus(e,today)===status)&&(!place||e.work_location===place)&&(!schedule||e.work_schedule===schedule));
}
const employeeWorkspace={selected:null,tab:'main',epoch:0,item:null};
function employeeNode(tag,text,className){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;}
function employeeFields(title,values){const section=employeeNode('section',null,'ui-card');const heading=employeeNode('h3',title);if(['Личные данные','Рабочие параметры'].includes(title)){const icon=uiIcon(title==='Личные данные'?'user':'settings');icon.classList.add('section-icon');heading.prepend(icon);}section.append(heading);const dl=employeeNode('dl',null,'ui-fields');for(const [key,value] of values){dl.append(employeeNode('dt',key),employeeNode('dd',value??'—'));}section.append(dl);return section;}
function renderEmployeeWorkspace(items){
    const $=id=>document.getElementById(id),state=employeeWorkspace;
    const rows=filterEmployeeWorkspace(items,$('employeeSearchInput').value,$('employeeStatusFilter').value,$('employeePlaceFilter').value,$('employeeScheduleFilter').value);
    $('employeeCount').textContent=`Показано: ${rows.length} из ${items.length}`;
    const list=$('employeeList');list.replaceChildren();
    if(!rows.some(e=>e.id===state.selected))state.selected=rows[0]?.id??null;
    if(!rows.length)list.append(employeeNode('div','Сотрудники не найдены','ui-empty'));
    else{
        const table=employeeNode('table',null,'ui-table'),head=employeeNode('thead'),tr=employeeNode('tr');
        for(const label of ['№','ФИО','Должность','Место','График','Статус']){const th=employeeNode('th',label);th.scope='col';tr.append(th);}head.append(tr);table.append(head);
        const body=employeeNode('tbody');rows.forEach((item,index)=>{
            const row=employeeNode('tr');row.dataset.employee=item.id;row.setAttribute('aria-selected',String(item.id===state.selected));
            const name=employeeNode('button',item.full_name);name.type='button';name.setAttribute('aria-label',`Открыть карточку: ${item.full_name}`);
            for(const value of [index+1,name,item.position_name,employeeChip(({OBJECT:'Объект',OFFICE:'Офис'})[item.work_location]||'—',item.work_location==='OBJECT'?'blue':'neutral'),employeeChip(({SHIFT:'Вахта',FIVE_TWO:'5/2'})[item.work_schedule]||'—',item.work_schedule==='SHIFT'?'blue':'neutral'),employeeChip(employeeStatus(item)+(item.is_archived?' · Архив':''),employeeStatus(item)==='Уволен'?'red':'green')]){
                const td=employeeNode('td');if(value instanceof Node)td.append(value);else td.textContent=value??'—';row.append(td);
            }
            row.onclick=()=>{state.selected=item.id;renderEmployeeWorkspace(items);employeeCardOpen(true);};body.append(row);
        });table.append(body);list.append(table);
    }
    const item=rows.find(e=>e.id===state.selected);
    if(state.item!==item){state.item=item;if(state.editingId!==item?.id)renderEmployeeProfile();}
}
async function employeeRead(url){const r=await fetch(url);const data=await r.json();if(!r.ok)throw Error(data.message||'Не удалось загрузить данные');return data;}
async function renderEmployeeProfile(){
    employeeWorkspace.editingId=null;
    const state=employeeWorkspace,item=state.item,epoch=++state.epoch,card=document.getElementById('employeeProfile');card.replaceChildren();
    if(!item){card.append(employeeNode('div','Выберите сотрудника в списке','ui-empty'));return;}
    const title=employeeNode('div',null,'employee-card-title'),back=employeeNode('button','← К списку сотрудников','ui-button');back.type='button';back.onclick=()=>employeeCardOpen(false);title.append(back,employeeNode('h2','Карточка сотрудника'));card.append(title);
    const place=({OBJECT:'Объект',OFFICE:'Офис'})[item.work_location]||'Место не задано',schedule=({SHIFT:'Вахта',FIVE_TWO:'5/2'})[item.work_schedule]||'График не задан';
    const header=employeeNode('div',null,'employee-profile-header'),identity=employeeNode('div',null,'employee-identity'),contact=employeeNode('div',null,'employee-contact');
    identity.append(employeeNode('h2',item.full_name),employeeNode('p',item.position_name||'Должность не указана','ui-muted'));
    const phone=employeeNode('p',item.phone||'Телефон не указан');phone.prepend(uiIcon('phone'));const nrs=employeeNode('p',`№ НРС: ${item.nrs_number||'—'}`);nrs.prepend(uiIcon('id'));contact.append(phone,employeeNode('p',`Email: ${item.email||'—'}`),nrs,employeeNode('p',`Статус: ${employeeStatus(item)}${item.dismissal_date?' · '+luvrLocalDate(item.dismissal_date):''}`));header.append(identity,contact);card.append(header);
    if(typeof mountEmployeeTransfers==='function')mountEmployeeTransfers(item,identity,card,()=>epoch===state.epoch);
    const badges=employeeNode('div');const stateBadge=employeeNode('span',item.dismissal_date&&item.dismissal_date<=employeeToday()?'Уволен':'Загрузка…','ui-badge');stateBadge.id='employeeStateBadge';
    badges.className='employee-header-badges';badges.append(employeeChip(place,item.work_location==='OBJECT'?'blue':'neutral',item.work_location==='OBJECT'?'object':'office'),stateBadge);identity.append(badges);
    const actions=employeeNode('div',null,'employee-profile-actions');
    const edit=employeeNode('button','Редактировать','ui-button ui-button-primary');edit.prepend(uiIcon('edit'));edit.type='button';edit.onclick=()=>editEmployeeCard(state.item);actions.append(edit);
    const archive=employeeNode('button',item.is_archived?'Восстановить':'В архив','ui-button');archive.type='button';
    archive.onclick=async()=>{archive.disabled=true;try{if(await changeEmployeeArchive(item,async(url,options)=>{const r=await fetch(url,options);const x=await r.json();if(!r.ok)throw Error(x.message||'Не удалось изменить архивное состояние');return x;},message=>confirm(message)))await loadEmployees();}catch(e){card.append(employeeNode('p',e.message,'ui-error'));}finally{archive.disabled=false;}};actions.append(archive);contact.append(actions);
    const tabs=employeeNode('div',null,'ui-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Карточка сотрудника');
    for(const [key,label] of [['main','Основные данные'],['history','История'],['assignments','Экипаж и объекты'],['equipment','Оборудование и ТМЦ'],['training','Обучение и аттестация']]){
        const button=employeeNode('button',label,'ui-tab');button.prepend(uiIcon(({main:'user',history:'calendar',assignments:'truck',equipment:'box',training:'graduation'})[key]));button.type='button';button.id='employeeProfileTab-'+key;button.setAttribute('role','tab');button.setAttribute('aria-selected',String(state.tab===key));button.setAttribute('aria-controls','employeeProfilePanel');button.onclick=()=>{state.tab=key;renderEmployeeProfile();document.getElementById(button.id)?.focus();};tabs.append(button);
    }card.append(tabs);const panel=employeeNode('div',null,'ui-stack');panel.id='employeeProfilePanel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','employeeProfileTab-'+state.tab);card.append(panel);card.insertBefore(employeeQuickActions(item),tabs);
    const stillCurrent=()=>epoch===state.epoch;
    const absenceData=employeeRead(`/api/employees/${item.id}/absences`);
    const dayData=employeeRead(`/api/employees/${item.id}/luvr/calendar/day?target=${employeeToday()}`);
    Promise.allSettled([absenceData,dayData]).then(([absences,day])=>{if(!stillCurrent())return;
        const records=absences.status==='fulfilled'?absences.value.items:null,label=employeeCurrentState(item,records,day.status==='fulfilled'?day.value.item:null,employeeToday());
        employeePaintState(stateBadge,label,employeeStateTone(item,records,label,employeeToday()));
        if(absences.status==='rejected'||day.status==='rejected')stateBadge.title='Не удалось загрузить все данные состояния';
    });
    const sectionAsync=async(title,work)=>{const host=employeeNode('section',null,'ui-card');host.append(employeeNode('h3',title),employeeNode('p','Загрузка…','ui-muted'));panel.append(host);try{const content=await work();if(stillCurrent()){host.replaceChildren(employeeNode('h3',title));host.append(content);}}catch(e){if(stillCurrent())host.replaceChildren(employeeNode('h3',title),employeeNode('p',e.message,'ui-error'));}};
    if(state.tab==='main'){
        panel.classList.add('employee-data-columns');

        const work=employeeFields('Рабочие параметры',[['Место работы',place],['График',schedule],['Специальность (из должности)',item.specialty],['Максимальная вахта, дней',item.max_shift_days],['Максимальная МВ, дней',item.max_off_shift_days]]);work.classList.add("employee-work-parameters");panel.append(work);
        const duration=employeeDurationBlock(item);work.append(duration.block);
        const details=employeeCardSections(item,panel,stillCurrent,absenceData);
        try{const today=employeeToday(),[year,month]=today.split('-');const data=(await employeeRead(`/api/luvr/month?year=${year}&month=${Number(month)}&as_of_date=${today}`)).item;
            if(stillCurrent()){const employee=data.employees.find(e=>e.employee_id===item.id);duration.update(employee?.duration);if(!employee)work.append(employeeNode('p','Нет расчёта: сотрудник не включён в ЛУВР текущего месяца.','ui-muted'));}
        }catch(e){if(stillCurrent()){duration.update(null);work.append(employeeNode('p',e.message,'ui-error'));}}
    await details;
    }else if(state.tab==='history'){
        const manage=employeeNode('button','Прибыл / Убыл','ui-button');manage.type='button';
        const manageHistory=async()=>{await openEmployeeModal(item);const block=document.getElementById('employeeLuvrHistory');block.open=true;block.scrollIntoView({block:'nearest'});};manage.onclick=manageHistory;panel.append(manage);
        const historySection=(kind,title)=>sectionAsync(title,async()=>{
            const {items}=await employeeRead(`/api/employees/${item.id}/luvr/${kind}`);const list=employeeNode('div',null,'ui-stack');if(!items.length)list.append(employeeNode('p','Записей пока нет','ui-empty'));
            if(kind==='duration-exceptions'){const edit=employeeNode('button','Управлять исключениями','ui-button');edit.type='button';edit.onclick=manageHistory;list.append(edit);}
            for(const record of items){const entry=employeeNode('div',luvrHistoryLabel(kind,record));if(record.comment)entry.append(employeeNode('p',record.comment,'ui-muted'));list.append(entry);}return list;
        });
        await Promise.all([historySection('movements','История перемещений'),sectionAsync('Отсутствия',async()=>renderEmployeeAbsences(item,(await absenceData).items)),historySection('duration-exceptions','Согласованные исключения')]);
    }else if(state.tab==='assignments'){
        const manage=employeeNode('button','Изменить экипаж и назначения','ui-button');manage.type='button';manage.onclick=()=>openEmployeeModal(item);panel.append(manage);
        await Promise.all([sectionAsync('Экипаж',async()=>{if(!item.crew_id)return employeeNode('p','Экипаж не назначен','ui-empty');const crew=(await employeeRead('/api/crews')).items.find(c=>c.id===item.crew_id);return employeeFields('Данные экипажа',[['Экипаж',crew?.name||item.crew_name],['Водитель',crew?.driver_full_name],['Телефон',crew?.driver_phone],['Автомобиль',[crew?.vehicle_make,crew?.vehicle_plate].filter(Boolean).join(' ')||'—']]);}),sectionAsync('Закреплённые объекты',async()=>{const {items}=await employeeRead(`/api/employees/${item.id}/assignments`);const list=employeeNode('div',null,'ui-stack');if(!items.length)list.append(employeeNode('p','Назначений пока нет','ui-empty'));for(const a of items)list.append(employeeFields(a.object_name,[['Подобъект',a.subobject_name||'Отдельное закрепление не задано'],['ПО',a.po_name],['Категория',a.category_name]]));return list;})]);
    }else panel.append(employeeNode('div','Раздел будет добавлен позже','ui-empty'));
}
if(typeof document!=='undefined'){
    for(const id of ['employeeStatusFilter','employeePlaceFilter','employeeScheduleFilter'])document.getElementById(id)?.addEventListener('change',()=>renderEmployees());
    document.addEventListener('employee-saved',e=>{employeeWorkspace.selected=e.detail.id;employeeWorkspace.item=null;});
    document.getElementById('employeeModal')?.addEventListener('click',()=>{if(document.getElementById('employeeModal').hidden)renderEmployeeProfile();});
}
if(typeof module!=='undefined')module.exports={employeeStatus,filterEmployeeWorkspace};
