/* Ticket employee selection reuses the employee modal and its POST/save handler. */
function railNormalizedName(value){return (value||'').trim().replace(/\s+/gu,' ').toLocaleLowerCase('ru');}
function railEmployeeCandidates(name,employees){
    const normalized=railNormalizedName(name),surname=normalized.split(' ')[0];
    if(!normalized)return [];
    return employees.filter(e=>{const n=railNormalizedName(e.full_name),parts=n.split(' ');return n===normalized||parts[0]===surname||parts.filter(p=>normalized.split(' ').includes(p)).length>=2;})
        .sort((a,b)=>Number(railNormalizedName(b.full_name)===normalized)-Number(railNormalizedName(a.full_name)===normalized)||a.id-b.id);
}
function railEmployeeControls(item,controller){
    if(!item.id||item.processing_status!=='EMPLOYEE_NOT_FOUND')return null;
    const box=document.createElement('div');box.className='ticket-detail-section';
    const note=document.createElement('p');note.textContent=item.match_ambiguous?'Найдено несколько сотрудников с одинаковым ФИО. Выберите вручную.':'Сотрудник не найден в базе данных';box.append(note);
    const button=(text,action)=>{const b=document.createElement('button');b.type='button';b.className='secondary-button';b.textContent=text;b.disabled=controller.pending.has(item.id);b.onclick=action;return b;};
    const refreshEmployees=async()=>{const result=await railRequest('/api/employees?include_archived=true');controller.employees=result.items||[];};
    const selectEmployee=async employee=>{controller.employeeSelections.set(item.id,employee.id);await controller.action(item.id,'refresh');};
    const candidates=railEmployeeCandidates(item.full_name,controller.employees||[]);
    const select=document.createElement('select');select.setAttribute('aria-label','Сотрудник для билета');select.id='railEmployeeSelect';select.add(new Option('Выберите сотрудника вручную',''));
    const ordered=[...candidates,...(controller.employees||[]).filter(e=>!candidates.some(c=>c.id===e.id))];
    for(const employee of ordered){const option=new Option(`${employee.full_name} · ${employee.position_name||'Должность не указана'} · № ${employee.id}${employee.is_archived?' · Архив':''}`,employee.id);option.disabled=employee.is_archived;select.add(option);}
    select.value=controller.employeeSelections.get(item.id)||'';
    select.onchange=()=>{controller.employeeSelections.delete(item.id);if(select.value)controller.employeeSelections.set(item.id,Number(select.value));controller.render(controller);};
    if(candidates.length){const info=document.createElement('p');info.textContent='Найдены совпадающие или похожие ФИО — проверьте варианты. Автоматический выбор не выполняется.';box.append(info);}
    box.append(select);
    if(select.value)box.append(button('Подтвердить выбранного сотрудника',()=>controller.action(item.id,'confirm',Number(select.value))));
    const showExisting=employees=>{
        document.getElementById('employeeTicketMatches')?.remove();
        if(!employees.length)return;
        const area=document.createElement('div');area.id='employeeTicketMatches';area.className='ticket-detail-section';
        const text=document.createElement('p');text.textContent='Такое ФИО уже существует. Выберите сотрудника вместо создания дубля:';area.append(text);
        for(const employee of employees){const b=button(`${employee.full_name} · № ${employee.id}${employee.is_archived?' · Архив':''}`,async()=>{closeEmployeeModal();await selectEmployee(employee);});b.disabled=employee.is_archived;area.append(b);}
        document.getElementById('employeeModalError').after(area);
    };
    const existing=()=> (controller.employees||[]).filter(e=>railNormalizedName(e.full_name)===railNormalizedName(document.getElementById('employeeNameInput').value));
    box.append(button('Добавить сотрудника',async()=>{
        await openEmployeeModal(null,{
            full_name:railEmployeeName(item.full_name),
            beforeSave:async body=>{
                if(!body.position_id)throw Error('Выберите должность сотрудника');
                await refreshEmployees();const matches=existing();showExisting(matches);
                if(matches.length)throw Error('ФИО уже существует. Выберите найденного сотрудника.');
            },
            onSaved:async employee=>{await selectEmployee(employee);await refreshEmployees();controller.render(controller);},
            onError:async()=>{try{await refreshEmployees();showExisting(existing());}catch{/* Keep entered fields and the original save error. */}}
        });
    }));
    return box;
}
if(typeof module!=='undefined')module.exports={railNormalizedName,railEmployeeCandidates};
