const objectActivityLabels={ACTIVE:'Действующий',SUSPENDED:'Приостановлен',COMPLETED:'Завершён'};
function objectArchiveControls(host,item,kind){
    const controls=directoryNode('div',null,'directory-actions object-archive-controls');
    const archived=item.is_archived||item.parent_is_archived;
    host.classList.toggle('object-archived',Boolean(archived));
    const state=directoryNode('span',item.is_archived?'В архиве':item.parent_is_archived?'Родитель в архиве':'Действующая запись','ui-muted');controls.append(state);
    const label=directoryNode('label','Статус деятельности '),select=directoryNode('select');
    for(const [value,text] of Object.entries(objectActivityLabels))select.add(new Option(text,value));select.value=item.activity_status||'ACTIVE';label.append(select);controls.append(label);
    const button=directoryNode('button',item.is_archived?'Восстановить':'В архив','ui-button');button.type='button';controls.append(button);
    async function change(suffix,method,body){
        button.disabled=true;select.disabled=true;
        try{const r=await fetch(`/api/${kind}/${item.id}/${suffix}`,{method,headers:{'Content-Type':'application/json'},body:body&&JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(result.message||'Не удалось изменить запись');await loadObjects();}
        catch(error){select.value=item.activity_status||'ACTIVE';alert(error.message);}
        finally{button.disabled=false;select.disabled=false;}
    }
    button.onclick=()=>{if(!item.is_archived&&!confirm(`Переместить «${item.name}» в архив? История и связи сохранятся.`))return;change(item.is_archived?'restore':'archive','POST');};
    select.onchange=()=>change('activity-status','PATCH',{activity_status:select.value});
    host.append(controls);
}
