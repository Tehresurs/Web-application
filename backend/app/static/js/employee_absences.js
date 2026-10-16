function employeeCurrentState(item,absences,day,today){
    if(item.dismissal_date&&item.dismissal_date<=today)return 'Уволен';
    if(!Array.isArray(absences))return 'Не определено';
    const reasons=[...new Set(absences.filter(a=>a.date_from<=today&&(!a.date_to||today<=a.date_to)).map(a=>a.reason))];
    if(reasons.length)return reasons.join(' / ');
    if(!day||day.calculation_status!=='CALCULATED')return 'Не определено';
    if(item.work_location==='OBJECT')return ({ON_SHIFT:'Вахта',OFF_SHIFT:'МВ'})[day.state]||'Не определено';
    if(item.work_location==='OFFICE'){
        if(day.final_code==='FULL'||day.final_code==='HALF')return 'Рабочий день';
        if(day.final_source_type==='WEEKEND'||day.state==='OFF_SHIFT')return 'Выходной';
    }
    return 'Не определено';
}
async function employeeAbsenceRequest(url,method,payload){
    const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(payload?{body:JSON.stringify(payload)}:{})});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw Error(data?.message||'Не удалось сохранить отсутствие. Проверьте поля формы.');
    return data;
}
function renderEmployeeAbsences(item,records){
    const root=employeeNode('div',null,'ui-stack'),toolbar=employeeNode('div',null,'employee-profile-actions');
    const add=employeeNode('button','+ Другое','ui-button'),dismiss=employeeNode('button','Уволен','ui-button');
    add.type=dismiss.type='button';toolbar.append(add,dismiss);root.append(toolbar);
    const editor=employeeNode('div');root.append(editor);
    const showEditor=(record=null,dismissal=false)=>{
        editor.replaceChildren();const form=employeeNode('form',null,'ui-card ui-stack');form.dataset.absenceForm=dismissal?'dismissal':'other';
        form.append(employeeNode('h4',dismissal?'Уволен':record?'Изменить «Другое»':'Другое'));
        const inputs={};
        function input(key,label,type,value,required){const wrap=employeeNode('label',label);const control=employeeNode(type==='textarea'?'textarea':'input',null,'ui-input');if(type!=='textarea')control.type=type;control.name=key;control.value=value||'';control.required=required;wrap.append(control);form.append(wrap);inputs[key]=control;}
        if(!dismissal)input('reason','Причина','text',record?.reason,true);
        input('date_from',dismissal?'Дата увольнения':'Дата начала','date',dismissal?item.dismissal_date:record?.date_from,true);
        if(!dismissal){input('date_to','Дата окончания','date',record?.date_to,record?.source!=='sick');input('comment','Комментарий','textarea',record?.comment,false);inputs.reason.maxLength=500;}
        if(record?.source==='sick')form.append(employeeNode('p','Существующий период болезни. Его участие в расчёте ЛУВР сохраняется; изменение названия не меняет вид расчёта.','ui-muted'));
        const error=employeeNode('p',null,'ui-error');error.hidden=true;form.append(error);
        const buttons=employeeNode('div',null,'employee-profile-actions'),save=employeeNode('button','Сохранить','ui-button ui-button-primary'),cancel=employeeNode('button','Отмена','ui-button');save.type='submit';cancel.type='button';cancel.onclick=()=>editor.replaceChildren();buttons.append(save,cancel);form.append(buttons);
        form.onsubmit=async event=>{event.preventDefault();save.disabled=true;error.hidden=true;
            try{
                if(dismissal){
                    const current=(await employeeRead('/api/employees?include_archived=true')).items.find(e=>e.id===item.id);
                    if(!current)throw Error('Сотрудник не найден');
                    await employeeAbsenceRequest(`/api/employees/${item.id}`,'PATCH',{full_name:current.full_name,position_id:current.position_id,phone:current.phone,crew_id:current.crew_id,dismissal_date:inputs.date_from.value});
                    await loadEmployees();
                }else{
                    const url=`/api/employees/${item.id}/absences`+(record?`/${record.source}/${record.id}`:'');
                    await employeeAbsenceRequest(url,record?'PATCH':'POST',{reason:inputs.reason.value.trim(),date_from:inputs.date_from.value,date_to:inputs.date_to.value||null,comment:inputs.comment.value.trim()||null});
                    if(employeeWorkspace.selected===item.id)renderEmployeeProfile();
                }
            }catch(e){error.textContent=e.message;error.hidden=false;}finally{save.disabled=false;}
        };editor.append(form);(inputs.reason||inputs.date_from).focus();
    };
    add.onclick=()=>showEditor();dismiss.onclick=()=>showEditor(null,true);
    if(item.dismissal_date)root.append(employeeFields('Уволен',[['Дата увольнения',luvrLocalDate(item.dismissal_date)]]));
    if(!records.length)root.append(employeeNode('p','Периодов отсутствия пока нет','ui-empty'));
    for(const record of records){
        const row=employeeFields(record.reason,[['Период',`${luvrLocalDate(record.date_from)} — ${record.date_to?luvrLocalDate(record.date_to):'открыт'}`],['Комментарий',record.comment]]);row.dataset.absenceId=record.id;row.dataset.absenceSource=record.source;
        const edit=employeeNode('button','Изменить','ui-button'),remove=employeeNode('button','Удалить','ui-button');edit.type=remove.type='button';edit.onclick=()=>showEditor(record);
        remove.onclick=async()=>{if(!confirm(`Удалить отсутствие «${record.reason}»?`))return;remove.disabled=true;try{await employeeAbsenceRequest(`/api/employees/${item.id}/absences/${record.source}/${record.id}`,'DELETE');if(employeeWorkspace.selected===item.id)renderEmployeeProfile();}catch(e){row.append(employeeNode('p',e.message,'ui-error'));}finally{remove.disabled=false;}};
        const actions=employeeNode('div',null,'employee-profile-actions');actions.append(edit,remove);row.append(actions);root.append(row);
    }
    return root;
}
if(typeof module!=='undefined')module.exports={employeeCurrentState};
