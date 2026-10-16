/* Form snapshots are used for optimistic concurrency; employees remain the source of membership. */
async function renderCrewMembers(card, crew) {
    const host=directoryNode('section',null,'crew-members ui-card');card.append(host);
    host.append(directoryNode('p','Загрузка состава…','ui-muted'));
    let snapshot=[], selected=new Map(), busy=false;
    const message=directoryNode('p',null,'ui-error');message.setAttribute('role','alert');
    async function refresh() {
        const response=await fetch('/api/employees?include_archived=true');
        const data=await response.json();
        if(!response.ok)throw Error(data.message||'Не удалось загрузить сотрудников');
        snapshot=data.items||[];selected.clear();
        if(host.isConnected)draw();
    }
    async function save(target, records) {
        if(busy)return;
        const transfers=records.filter(e=>target!==null&&e.crew_id!==null&&e.crew_id!==target);
        if(transfers.length&&!confirm('Перевести сотрудников в этот экипаж?\n'+transfers.map(e=>`${e.full_name} — ${e.crew_name||'Экипаж № '+e.crew_id}`).join('\n')))return;
        busy=true;message.textContent='';host.querySelectorAll('button,input').forEach(e=>e.disabled=true);
        try {
            const response=await fetch('/api/crew-memberships',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({
                target_crew_id:target,employees:records.map(e=>({employee_id:e.id,expected_crew_id:e.crew_id??null})),confirm_transfers:transfers.length>0
            })});
            const data=await response.json();
            if(!response.ok){
                if(response.status===409)await refresh();
                throw Error(data.message||'Не удалось сохранить состав');
            }
            await refresh();
            await loadEmployees();
        }catch(error){message.textContent=error.message;if(host.isConnected)host.append(message);}
        finally{busy=false;host.querySelectorAll('button,input').forEach(e=>e.disabled=false);}
    }
    function draw() {
        host.replaceChildren();
        const members=snapshot.filter(e=>e.crew_id===crew.id);
        host.append(directoryNode('h3',`Состав экипажа (${members.length})`));
        if(!members.length)host.append(directoryNode('p','Нет закреплённых сотрудников','ui-empty'));
        for(const e of members){
            const row=directoryNode('div',null,'crew-member');
            row.append(directoryNode('span',`${e.full_name} · ${e.position_name||'Должность не указана'}${e.is_archived?' · В архиве':''}`));
            const remove=directoryNode('button','Исключить из экипажа','ui-button');remove.type='button';remove.onclick=()=>save(null,[e]);row.append(remove);host.append(row);
        }
        const add=directoryNode('button','Добавить сотрудников','ui-button');add.type='button';host.append(add,message);
        add.onclick=()=>{
            add.hidden=true;
            const form=directoryNode('div',null,'ui-fields crew-member-picker');
            const search=directoryNode('input');search.type='search';search.placeholder='Поиск по ФИО';search.setAttribute('aria-label','Поиск сотрудников по ФИО');
            const list=directoryNode('div',null,'crew-candidates');
            const apply=directoryNode('button','Закрепить выбранных (0)','ui-button');apply.type='button';
            const cancel=directoryNode('button','Отмена','ui-button');cancel.type='button';cancel.onclick=()=>{selected.clear();draw();};
            function candidates(){
                list.replaceChildren();
                const items=snapshot.filter(e=>!e.is_archived&&e.crew_id!==crew.id&&e.full_name.toLocaleLowerCase('ru').includes(search.value.trim().toLocaleLowerCase('ru')));
                if(!items.length)list.append(directoryNode('p','Сотрудники не найдены','ui-empty'));
                for(const e of items){
                    const label=directoryNode('label',null,'crew-candidate'),check=directoryNode('input');check.type='checkbox';check.checked=selected.has(e.id);check.dataset.employeeId=e.id;
                    check.onchange=()=>{if(check.checked)selected.set(e.id,e);else selected.delete(e.id);apply.textContent=`Закрепить выбранных (${selected.size})`;};
                    label.append(check,directoryNode('span',`${e.full_name} · ${e.position_name||'Должность не указана'} — ${e.crew_id?(e.crew_name||'Экипаж № '+e.crew_id)+' (перевод)':'Без экипажа'}`));list.append(label);
                }
            }
            search.oninput=candidates;apply.onclick=()=>{if(selected.size)save(crew.id,[...selected.values()]);};
            form.append(search,list,apply,cancel);host.append(form);candidates();search.focus();
        };
    }
    try{await refresh();}catch(error){host.replaceChildren(directoryNode('p',error.message,'ui-error'));}
}
