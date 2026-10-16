function employeeStateTone(item,absences,label,today){
    if(item.dismissal_date&&item.dismissal_date<=today)return 'red';
    if(absences?.some(a=>a.date_from<=today&&(!a.date_to||today<=a.date_to)))return 'orange';
    return ({'Вахта':'green','Рабочий день':'green','МВ':'blue','Выходной':'blue'})[label]||'neutral';
}
function employeeChip(text,tone,icon){const chip=employeeNode('span',null,`ui-badge badge-${tone}`);if(icon)chip.append(uiIcon(icon));chip.append(document.createTextNode(text));return chip;}
function employeePaintState(node,text,tone){node.className=`ui-badge badge-${tone}`;node.replaceChildren(uiIcon(({green:'check',blue:'clock',orange:'calendar',red:'close'})[tone]||'clock'),document.createTextNode(text));}
function employeeDurationValues(duration){
    const shift=duration?.current_shift_days,off=duration?.current_off_shift_days;
    return {shift:shift??(duration?.current_state==='OFF_SHIFT'&&typeof off==='number'?0:'—'),off:off??(duration?.current_state==='ON_SHIFT'&&typeof shift==='number'?0:'—')};
}
function employeeDurationBlock(item){
    const block=employeeNode('section',null,'status-highlight'),heading=employeeNode('h4','Текущее состояние');heading.prepend(uiIcon('calendar'));block.append(heading);
    const list=employeeNode('dl',null,'employee-duration-values');
    const rows={};
    for(const [key,label,max] of [['shift','Вахта',item.max_shift_days],['off','МВ',item.max_off_shift_days]]){
        const row=employeeNode('div'),value=employeeNode('span','…');value.dataset.durationValue=key;
        const dd=employeeNode('dd');dd.append(value,employeeNode('span',` / ${max??'—'} дней`,'ui-muted'));row.append(employeeNode('dt',label),dd);list.append(row);rows[key]={row,value};
    }
    block.append(list);
    return {block,update(duration){const values=employeeDurationValues(duration);rows.shift.value.textContent=values.shift;rows.off.value.textContent=values.off;rows.shift.row.classList.toggle('duration-active-green',duration?.current_state==='ON_SHIFT');rows.off.row.classList.toggle('duration-active-blue',duration?.current_state==='OFF_SHIFT');}};
}
function employeeQuickActions(item){
    const section=employeeNode('section',null,'employee-quick-actions');const heading=employeeNode('h3','Быстрые действия');heading.prepend(uiIcon('bolt'));section.append(heading);
    const grid=employeeNode('div',null,'employee-quick-grid'),error=employeeNode('p',null,'ui-error');error.hidden=true;
    async function history(kind){await openEmployeeModal(item);const block=document.getElementById('employeeLuvrHistory');block.open=true;await employeeLuvrController.load();const button=block.querySelector(`[data-kind="${kind}"] > button`);if(!button)throw Error('Не удалось открыть форму истории');button.click();block.querySelector(`[data-kind="${kind}"] .luvr-history-editor`)?.scrollIntoView({block:'nearest'});}
    const actions=[
        ['calendar','Открыть ЛУВР','blue',async()=>{await document.getElementById('luvrCalendarNavButton').onclick();const select=document.getElementById('luvrCalendarEmployee');select.value=String(item.id);if(select.value!==String(item.id))throw Error('Сотрудник не найден в календаре');document.getElementById('luvrCalendarMonth').value=employeeToday().slice(0,7);await select.onchange();}],
        ['truck','Добавить перемещение','green',()=>history('movements')],
        ['plus','Добавить отсутствие','blue',async()=>{employeeWorkspace.tab='history';await renderEmployeeProfile();if(employeeWorkspace.selected!==item.id)return;const button=Array.from(document.querySelectorAll('#employeeProfilePanel button')).find(b=>b.textContent==='+ Другое');if(!button)throw Error('Не удалось загрузить отсутствия');button.click();button.scrollIntoView({block:'nearest'});}],
        ['alert','Добавить исключение','orange',()=>history('duration-exceptions')]
    ];
    for(const [icon,label,tone,action] of actions){const b=employeeNode('button',label,`ui-button action-${tone}`);b.type='button';b.prepend(uiIcon(icon));b.dataset.quickAction=icon;b.onclick=async()=>{b.disabled=true;error.hidden=true;try{await action();}catch(e){error.textContent=e.message;error.hidden=false;}finally{b.disabled=false;}};grid.append(b);}
    section.append(grid,error);return section;
}
if(typeof module!=='undefined')module.exports={employeeStateTone,employeeDurationValues};
