/* Actual card/API integration. User/role/CSRF are validated by the server. */
async function personnelRequest(url,options={}){
    async function loginRouteAvailable(){
        if(typeof window==='undefined'||!window.location||window.location.pathname==='/login')return false;
        try{
            const probe=await fetch('/login',{method:'HEAD',credentials:'same-origin',cache:'no-store'});
            return probe.status!==404&&probe.status!==405;
        }catch{return false;}
    }
    async function requestLogin(){
        if(!(await loginRouteAvailable()))return false;
        const next=encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign('/login?next=' + next);
        return true;
    }
    if(options.method&&options.method!=='GET'){
        const base=url.split('/position-transfers')[0]+'/position-transfers';
        const capabilities=await fetch(base+'/capabilities',{credentials:'same-origin',cache:'no-store'});
        let capability={};
        try{capability=await capabilities.json();}catch{capability={};}
        if(!capabilities.ok){
            if(capabilities.status===401||capabilities.status===403){
                if(await requestLogin())throw Object.assign(Error('Кадровая операция недоступна'),{status:capabilities.status});
                throw Object.assign(Error('Кадровые операции недоступны в текущем режиме приложения'),{status:capabilities.status,noAuth:true});
            }
            throw Object.assign(Error('Кадровая операция недоступна'),{status:capabilities.status});
        }
        if(capability.item?.audit_source==='LOCAL_APP'){
            options={...options,headers:{...options.headers,'X-Personnel-Local-Token':capability.item.local_request_token}};
        }else{
            const me=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
            let identity={};
            try{identity=await me.json();}catch{identity={};}
            if(!me.ok){
                if(me.status===401||me.status===403){
                    if(await requestLogin())throw Object.assign(Error('Требуется действительная сессия'),{status:me.status});
                    throw Object.assign(Error('Кадровые операции недоступны в текущем режиме приложения'),{status:me.status,noAuth:true});
                }
                throw Object.assign(Error('Требуется действительная сессия'),{status:me.status});
            }
            options={...options,headers:{...options.headers,'X-CSRF-Token':identity.csrf_token}};
        }
    }
    const response=await fetch(url,options);
    let data={};
    try{data=await response.json();}catch{data={};}
    if(!response.ok){
        if(response.status===401||response.status===403){
            if(await requestLogin()){
                const error=Error(typeof data.detail==='string'?data.detail:data.message||'Не удалось выполнить кадровую операцию');error.status=response.status;throw error;
            }
            const error=Error('Кадровые операции недоступны в текущем режиме приложения');error.status=response.status;error.noAuth=true;throw error;
        }
        const error=Error(typeof data.detail==='string'?data.detail:data.message||'Не удалось выполнить кадровую операцию');error.status=response.status;throw error;
    }
    return data.item;
}
function personnelDate(value){return value?value.slice(0,10).split('-').reverse().join('.'):'по настоящее время';}
async function mountEmployeeTransfers(item,identity,card,valid){
    const base=`/api/employees/${item.id}/position-transfers`;
    // Reserve the action synchronously, together with the card header.
    const button=employeeNode('button','Перемещение сотрудников','ui-button action-blue');
    button.type='button';button.disabled=true;button.dataset.personnelTransfer=String(item.id);button.dataset.personnelWrite='transfer';
    const availability=employeeNode('p','Проверяем доступность кадровых операций…','ui-muted');
    availability.id=`personnelAvailability-${item.id}`;availability.setAttribute('role','status');
    availability.style.minHeight='3em';button.setAttribute('aria-describedby',availability.id);
    const unavailable=message=>{button.disabled=true;button.onclick=null;button.title=message;availability.textContent=message;};
    button.title=availability.textContent;identity.append(button,availability);
    try{
        // Both endpoints enforce access themselves. Load independent card data concurrently.
        const [caps,history]=await Promise.all([personnelRequest(base+'/capabilities'),personnelRequest(base)]);
        if(!valid())return;
        if(!caps.installed){unavailable('Кадровый модуль ещё не установлен');return;}
        const current=history.current;
        if(current?.status==='KNOWN'&&current.definition_status==='KNOWN'){
            const position=identity.querySelector('p.ui-muted');if(position)position.textContent=current.definition.name;
        }
        const actingNow=new Map();for(const event of history.acting_audit||[])actingNow.set(event.root_id,event);
        for(const event of actingNow.values())if(event.kind!=='CANCEL'&&event.starts_on<=employeeToday()&&employeeToday()<=event.ends_on){const raw=event.position_name;const label=raw==='Руководитель СК'?'И.О. Руководителя СК':/^И[.\s]*О[.\s]/i.test(raw)?raw:'И.О. '+raw;identity.append(employeeNode('p',`${label} · до ${personnelDate(event.ends_on)}`,'info-highlight'));}
        const section=employeeNode('section',null,'ui-card personnel-history');
        section.append(employeeNode('h3','История кадровых операций'));
        const known=history.baseline?.known_on;
        section.append(employeeNode('p',`Исходное наблюдение: ${history.baseline?.definition?.name||'должность не указана'}. Дата начала неизвестна${known?'; сведения подтверждены на '+personnelDate(known):''}.`,'ui-muted'));
        const table=employeeNode('table',null,'ui-table'),head=employeeNode('tr');
        for(const label of ['Должность','Период известных сведений','Состояние'])head.append(employeeNode('th',label));
        const thead=employeeNode('thead');thead.append(head);table.append(thead);const body=employeeNode('tbody');
        for(const period of history.periods){
            const row=employeeNode('tr'),definition=period.position?.definition;
            const end=period.known_to?new Date(Date.parse(period.known_to+'T00:00:00Z')-86400000).toISOString().slice(0,10):null;
            for(const text of [definition?.name||'Должность или её параметры неизвестны',personnelDate(period.known_from)+' — '+personnelDate(end),period.known_from>employeeToday()?'Запланирован':end&&end<employeeToday()?'Завершён':'Действует'])row.append(employeeNode('td',text));body.append(row);
        }table.append(body);const scroll=employeeNode('div',null,'ui-table-wrap');scroll.append(table);section.append(scroll);
        if(history.audit.length){const details=employeeNode('details');details.append(employeeNode('summary','Журнал оформления и исправлений'));
            for(const event of history.audit)details.append(employeeNode('p',`Версия ${event.version} · ${{TRANSFER:'Перевод',CORRECT:'Исправление',CANCEL:'Отмена'}[event.kind]} · ${event.actor_login} · ${event.reason||'Без основания'}`));section.append(details);}
        if(caps.can_review){
            const latest=new Map();for(const event of history.audit)latest.set(event.root_id,event);
            for(const event of latest.values())if(event.kind!=='CANCEL'){
                const actions=employeeNode('div',null,'personnel-actions');
                for(const [kind,label] of [['CORRECT','Исправить перевод'],['CANCEL','Отменить перевод']]){
                    const button=employeeNode('button',label,'ui-button');button.type='button';button.dataset.personnelWrite='transfer';button.dataset.personnelReview=kind;button.onclick=()=>openPersonnelReview(item,history,event,kind);actions.append(button);
                }section.append(actions);
            }
        }
        if(history.acting_audit?.length){const details=employeeNode('details');details.dataset.actingHistory='true';details.open=true;details.append(employeeNode('summary','Назначения И.О. и их изменения'));
            for(const event of history.acting_audit)details.append(employeeNode('p',`${{ASSIGN:'Назначение',CHANGE_END:'Изменение срока',END:'Завершение с планом',CANCEL:'Отмена'}[event.kind]} · ${event.position_name} · ${personnelDate(event.starts_on)} — ${personnelDate(event.ends_on)} · ${event.actor_login} · ${event.reason||'Без основания'}`));if(caps.can_review){const current=new Map();for(const e of history.acting_audit)current.set(e.root_id,e);for(const e of current.values())if(!['CANCEL','END'].includes(e.kind)){
                const actions=employeeNode('div',null,'personnel-actions');
                actions.append(employeeNode('p',`${e.position_name} · ${personnelDate(e.starts_on)} — ${personnelDate(e.ends_on)}`,'ui-muted'));
                for(const [kind,label] of [['CHANGE_END','Исправить срок И.О.'],['CANCEL','Удалить назначение И.О.']]){
                    const b=employeeNode('button',label,'ui-button');b.type='button';b.dataset.personnelWrite='transfer';
                    b.dataset.actingReview=kind;b.dataset.actingRoot=e.root_id;
                    b.onclick=()=>openActingReview(item,history,e,kind);actions.append(b);
                }details.append(actions);
            }}section.append(details);
        }
        card.append(section);
        if(caps.can_transfer){
            button.onclick=()=>openEmployeeTransfer(item,history,caps);button.disabled=false;button.title='Перемещение сотрудников';availability.textContent='';
        }else unavailable(caps.read_only?'Кадровые операции доступны только для просмотра':(caps.blockers||[]).join('. ')||'Кадровая запись недоступна');
    }catch(error){
        // A legacy server or anonymous page must never gain write authority.
        if(!valid())return;
        const message=error.noAuth?'Кадровые операции недоступны в текущем режиме приложения'
            :error.status===401?'Для кадровых операций требуется действительная пользовательская сессия'
            :error.status===403?'Нет доступа к кадровым операциям'
            :error.status===404?'Кадровый модуль недоступен на сервере'
            :'Не удалось проверить доступность кадровых операций: '+error.message;
        unavailable(message);
    }
}
async function openEmployeeTransfer(item,history,caps){
    if(!caps.can_transfer)return;
    const modal=document.createElement('dialog');modal.className='personnel-dialog';modal.setAttribute('aria-labelledby','personnelTransferTitle');
    const form=employeeNode('form'),title=employeeNode('h2','Перемещение сотрудников');title.id='personnelTransferTitle';form.append(title);
    function field(label,tag,type){const wrap=employeeNode('label',label),el=employeeNode(tag,null,'ui-input');if(type)el.type=type;wrap.append(el);form.append(wrap);return el;}
    const person=field('Сотрудник','select');person.name='employee_id';person.required=true;person.add(new Option(item.full_name,String(item.id)));
    form.append(employeeNode('p','Текущая основная должность: '+(history.current?.definition?.name||item.position_name||'не указана'),'ui-muted'));
    const operation=field('Тип кадровой операции','select');operation.name='operation';
    for(const [key,label] of [['TRANSFER','Постоянный перевод'],['ASSIGN','Временное назначение И.О.'],['END','Завершение И.О. с возвращением к инженерной работе']])operation.add(new Option(label,key));
    const position=field('Новая / временно исполняемая должность','select');position.required=true;position.name='position_id';position.add(new Option('Выберите должность',''));
    const day=field('Дата перевода / начала И.О.','input','date');day.name='effective_on';day.required=true;day.value=employeeToday();
    let sourcePositionId=null,sourceEpoch=0;
    const ending=field('Последний день И.О. (включительно)','input','date');ending.name='ends_on';
    const acting=field('Завершаемое назначение И.О.','select');acting.name='acting_root';
    const latest=new Map();for(const event of history.acting_audit||[])latest.set(event.root_id,event);
    acting.add(new Option('Выберите назначение',''));for(const e of latest.values())if(!['CANCEL','END'].includes(e.kind))acting.add(new Option(`${e.position_name}: ${personnelDate(e.starts_on)} — ${personnelDate(e.ends_on)}`,e.root_id));
    const objects=field('Объекты контроля (можно выбрать несколько)','select');objects.name='objects';objects.multiple=true;objects.size=5;
    const period=field('Действующий заезд для планового закрепления','select');period.name='arrival_movement_ref';
    const planEnd=field('Окончание явного периода (только для офисного графика 5/2)','input','date');planEnd.name='plan_end';
    const reason=field('Основание','textarea');reason.name='reason';reason.maxLength=2000;
    const impact=employeeNode('p',null,'info-highlight');impact.hidden=true;const error=employeeNode('p',null,'ui-error');error.setAttribute('role','alert');error.hidden=true;form.append(impact,error);
    const actions=employeeNode('div',null,'personnel-actions'),submit=employeeNode('button','Проверить операцию','ui-button ui-button-primary'),cancel=employeeNode('button','Отмена','ui-button');submit.type='submit';submit.dataset.personnelWrite='transfer';cancel.type='button';cancel.onclick=()=>modal.close();actions.append(submit,cancel);form.append(actions);
    form.append(employeeNode('p','Основная должность при И.О. сохраняется. Возвращение к инженерной работе начинается на следующий день после последнего дня И.О.','ui-muted'));
    modal.append(form);document.body.append(modal);modal.onclose=()=>modal.remove();modal.showModal();
    let confirmed=false,pending=false,planning=null,planningEpoch=0;modal.oncancel=e=>{if(pending)e.preventDefault();};let requestId=crypto.randomUUID();
    const reset=()=>{confirmed=false;impact.hidden=true;submit.textContent='Проверить операцию';error.textContent='';error.hidden=true;};
    for(const el of [position,day,ending,acting,objects,period,planEnd,reason])el.addEventListener('input',reset);
    const show=(el,visible,required=false)=>{el.parentElement.hidden=!visible;el.disabled=!visible;el.required=visible&&required;};
    function refresh(){const kind=operation.value;show(position,kind!=='END',true);show(day,kind!=='END',true);show(ending,kind!=='TRANSFER',true);show(acting,kind==='END',true);show(objects,kind==='END',true);show(period,kind==='END');show(planEnd,kind==='END'&&planning?.explicit_period_allowed,true);reason.required=kind==='END';reset();}
    async function loadPlanning(){if(operation.value!=='END'||!ending.value)return;const epoch=++planningEpoch;planning=null;period.replaceChildren();submit.disabled=true;
        try{const back=new Date(ending.value+'T00:00:00Z');back.setUTCDate(back.getUTCDate()+1);const loaded=await personnelRequest(`/api/employees/${item.id}/position-transfers/planning-context?on_day=${back.toISOString().slice(0,10)}`);if(epoch!==planningEpoch)return;planning=loaded;
            for(const p of planning.periods)period.add(new Option(`${personnelDate(p.date_from)} — ${personnelDate(p.date_to)}`,String(p.arrival_movement_ref)));
            refresh();if(!planning.explicit_period_allowed&&!planning.periods.length)throw Error('Нет действующего заезда для планового закрепления. Исправьте исходную историю отдельной операцией.');
        }catch(e){error.hidden=false;error.textContent=e.message;}finally{if(epoch===planningEpoch&&operation.value==='END'&&!pending)submit.disabled=false;}
    }
    async function loadPredecessor(){
        const epoch=++sourceEpoch;if(operation.value!=='TRANSFER')return;
        sourcePositionId=null;submit.disabled=true;reset();
        try{
            const value=await personnelRequest(`/api/employees/${item.id}/position-transfers/predecessor?on_day=${day.value}`);
            if(epoch!==sourceEpoch)return;
            const candidate=value.status==='UNKNOWN_HISTORY'
                ? (history.baseline?.position_id??history.current?.position_id??item.position_id)
                : value.position_id;
            if(!Number.isInteger(Number(candidate))||Number(candidate)<=0)throw Error('В карточке сотрудника не указана исходная должность');
            sourcePositionId=Number(candidate);
        }catch(e){if(epoch===sourceEpoch){error.hidden=false;error.textContent=e.message;}}
        finally{if(epoch===sourceEpoch&&operation.value==='TRANSFER'&&!pending)submit.disabled=sourcePositionId===null;}
    }
    day.addEventListener('change',loadPredecessor);
    operation.onchange=()=>{planningEpoch++;sourceEpoch++;submit.disabled=false;refresh();loadPlanning();loadPredecessor();};ending.addEventListener('change',loadPlanning);
    acting.onchange=()=>{const event=latest.get(acting.value);if(event){ending.value=event.ends_on;loadPlanning();}};
    person.onchange=async()=>{try{const rows=(await employeeRead('/api/employees')).items;const other=rows.find(e=>String(e.id)===person.value);const base=`/api/employees/${other.id}/position-transfers`;const newCaps=await personnelRequest(base+'/capabilities'),newHistory=await personnelRequest(base);modal.close();await openEmployeeTransfer(other,newHistory,newCaps);}catch(e){error.hidden=false;error.textContent=e.message;}};
    refresh();submit.disabled=true;
    try{const [catalog,employees,choices]=await Promise.all([employeeRead('/api/positions'),employeeRead('/api/employees'),ConstructionChoices.load(employeeRead)]);
        for(const p of catalog.items)position.add(new Option(p.name,String(p.id)));
        person.replaceChildren();for(const e of employees.items)person.add(new Option(e.full_name,String(e.id)));person.value=String(item.id);
        for(const row of ConstructionChoices.options(choices).rows)objects.add(new Option(row.label,row.value));
        await loadPredecessor();if(operation.value!=='TRANSFER')submit.disabled=false;
    }catch(e){error.textContent=e.message;error.hidden=false;submit.disabled=true;}
    form.onsubmit=async e=>{e.preventDefault();if(pending||!form.reportValidity())return;
        const kind=operation.value;
        if(!confirmed){impact.hidden=false;impact.textContent='Проверьте сотрудника, должность и даты. Данные сохранятся только после подтверждения.';confirmed=true;submit.textContent=kind==='TRANSFER'?'Подтвердить перевод':'Подтвердить';return;}
        pending=true;submit.disabled=cancel.disabled=true;error.hidden=true;
        const common={reason:reason.value.trim()||null,request_id:requestId,expected_version:history.version};let suffix='',payload;
        try{
            if(kind==='TRANSFER')payload={...common,position_id:Number(position.value),effective_on:day.value,source_position_id:sourcePositionId};
            else if(kind==='ASSIGN'){suffix='/acting';payload={...common,position_id:Number(position.value),starts_on:day.value,ends_on:ending.value};}
            else{
                if(!planning)throw Error('Дождитесь загрузки периода планирования');
                const back=new Date(ending.value+'T00:00:00Z');back.setUTCDate(back.getUTCDate()+1);const returnDay=back.toISOString().slice(0,10);
                const plan={effective_from:returnDay,period_kind:planning.explicit_period_allowed?'EXPLICIT':'ARRIVAL',arrival_movement_ref:planning.explicit_period_allowed?null:Number(period.value),period_start:planning.explicit_period_allowed?returnDay:null,period_end:planning.explicit_period_allowed?planEnd.value:null,source_kind:'MANUAL',assignment_state:'OBJECTS',items:Array.from(objects.selectedOptions,o=>ConstructionChoices.reference(o.value))};
                if(!plan.items.length)throw Error('Выберите хотя бы один объект');suffix=`/acting/${acting.value}/end`;payload={...common,ends_on:ending.value,plan};
            }
            await personnelRequest(`/api/employees/${item.id}/position-transfers${suffix}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            modal.close();await loadEmployees();document.dispatchEvent(new CustomEvent('employee-saved',{detail:{id:item.id}}));
        }catch(e){error.textContent=e.message;error.hidden=false;pending=false;submit.disabled=cancel.disabled=false;}
    };
}
if(typeof module!=='undefined')module.exports={personnelDate};

async function openPersonnelReview(item,history,event,kind){
    const modal=document.createElement('dialog');modal.className='personnel-dialog';
    const form=employeeNode('form');form.append(employeeNode('h2',kind==='CORRECT'?'Исправление перевода':'Отмена перевода'),employeeNode('p',item.full_name),employeeNode('p','Исходная запись остаётся в журнале.','ui-muted'));
    function field(label,tag,type){const wrap=employeeNode('label',label),el=employeeNode(tag,null,'ui-input');if(type)el.type=type;wrap.append(el);form.append(wrap);return el;}
    let position=null,day=null;
    if(kind==='CORRECT'){
        position=field('Новая должность','select');position.name='position_id';position.required=true;
        day=field('Исправленная дата вступления','input','date');day.name='effective_on';day.required=true;day.value=event.effective_on;
    }
    const reason=field('Основание исправления или отмены','textarea');reason.name='reason';reason.required=true;reason.maxLength=2000;
    const error=employeeNode('p',null,'ui-error');error.hidden=true;error.setAttribute('role','alert');form.append(error);
    const actions=employeeNode('div',null,'personnel-actions'),submit=employeeNode('button','Проверить операцию','ui-button ui-button-primary'),close=employeeNode('button','Закрыть','ui-button');
    submit.type='submit';submit.dataset.personnelWrite='transfer';close.type='button';close.onclick=()=>modal.close();actions.append(submit,close);form.append(actions);modal.append(form);document.body.append(modal);modal.onclose=()=>modal.remove();modal.showModal();
    let confirmed=false,pending=false;const requestId=crypto.randomUUID();
    for(const field of [position,day,reason].filter(Boolean))field.oninput=()=>{confirmed=false;submit.textContent='Проверить операцию';error.hidden=true;};
    if(position)try{const catalog=await employeeRead('/api/positions');for(const p of catalog.items)position.append(new Option(p.name,String(p.id)));position.value=String(event.position_id);}catch(e){error.hidden=false;error.textContent=e.message;submit.disabled=true;}
    form.onsubmit=async e=>{e.preventDefault();if(pending||!form.reportValidity())return;
        if(!reason.value.trim()){error.hidden=false;error.textContent='Укажите основание';return;}
        if(!confirmed){confirmed=true;submit.textContent=kind==='CORRECT'?'Сохранить исправление':'Подтвердить отмену перевода';return;}
        pending=true;submit.disabled=close.disabled=true;error.hidden=true;
        try{await personnelRequest(`/api/employees/${item.id}/position-transfers/${event.root_id}/${kind==='CORRECT'?'corrections':'cancellations'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({position_id:position?Number(position.value):null,effective_on:day?day.value:null,reason:reason.value.trim(),request_id:requestId,expected_version:history.version})});modal.close();await loadEmployees();}
        catch(e){error.hidden=false;error.textContent=e.message;pending=false;submit.disabled=close.disabled=false;}
    };
}


async function openActingReview(item,history,event,kind){
    const modal=document.createElement('dialog');modal.className='personnel-dialog';const form=employeeNode('form');form.append(employeeNode('h2',kind==='CANCEL'?'Удаление назначения И.О.':'Изменение срока И.О.'),employeeNode('p',item.full_name),employeeNode('p',`${event.position_name} · ${personnelDate(event.starts_on)} — ${personnelDate(event.ends_on)}`));
    if(kind==='CANCEL')form.append(employeeNode('p','Назначение перестанет действовать. Запись и причина отмены останутся в кадровой истории.','ui-muted'));
    let ends=null;if(kind!=='CANCEL'){const label=employeeNode('label','Последний день И.О. (включительно)');ends=employeeNode('input',null,'ui-input');ends.type='date';ends.required=true;ends.value=event.ends_on;label.append(ends);form.append(label);}
    const label=employeeNode('label',kind==='CANCEL'?'Причина удаления (обязательно)':'Основание (обязательно)'),reason=employeeNode('textarea',null,'ui-input');reason.name='reason';reason.required=true;reason.maxLength=2000;label.append(reason);form.append(label);
    const message=employeeNode('p',null,'ui-error');message.setAttribute('role','alert');form.append(message);const actions=employeeNode('div',null,'personnel-actions'),save=employeeNode('button','Проверить операцию','ui-button ui-button-primary'),cancel=employeeNode('button','Отмена','ui-button');save.type='submit';save.dataset.personnelWrite='transfer';cancel.type='button';cancel.onclick=()=>modal.close();actions.append(save,cancel);form.append(actions);modal.append(form);document.body.append(modal);modal.onclose=()=>modal.remove();modal.showModal();let confirmed=false,pending=false;const requestId=crypto.randomUUID();
    for(const el of [ends,reason].filter(Boolean))el.oninput=()=>{confirmed=false;save.textContent='Проверить операцию';};
    form.onsubmit=async e=>{e.preventDefault();if(pending||!form.reportValidity())return;if(!reason.value.trim()){message.textContent='Укажите основание';return;}if(!confirmed){confirmed=true;save.textContent=kind==='CANCEL'?'Подтвердить удаление назначения':'Подтвердить';return;}pending=true;save.disabled=cancel.disabled=true;
        try{await personnelRequest(`/api/employees/${item.id}/position-transfers/acting/${event.root_id}/${kind==='CANCEL'?'cancel':'end-date'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ends_on:ends?.value||null,reason:reason.value.trim(),request_id:requestId,expected_version:history.version})});modal.close();await loadEmployees();}catch(error){message.textContent=error.message;pending=false;save.disabled=cancel.disabled=false;}
    };
}
