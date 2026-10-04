/* Stored employee history only. Local dates are deliberately not passed through Date/UTC. */
const LUVR_HISTORY_KINDS = ['movements', 'sick-periods', 'duration-exceptions'];
function luvrHistoryPayload(kind, fields) {
    const optional = value => value?.trim() || null;
    if (kind === 'movements') {
        if (!fields.date || !fields.time) throw new Error('Укажите дату и время события');
        return {movement_type: fields.movement_type, transport_type: 'SELF',
            event_datetime: `${fields.date}T${fields.time}`, source_file: null,
            departure_station: optional(fields.departure_station), arrival_station: optional(fields.arrival_station)};
    }
    if (!fields.date_from) throw new Error('Укажите дату начала');
    if (fields.date_to && fields.date_to < fields.date_from) throw new Error('Дата окончания не может быть раньше даты начала');
    const payload = {date_from: fields.date_from, date_to: fields.date_to || null, comment: optional(fields.comment)};
    if (kind === 'duration-exceptions') {
        if (!payload.date_to || !payload.comment) throw new Error('Укажите дату окончания и комментарий');
        payload.exception_type = fields.exception_type;
    }
    return payload;
}
function luvrLocalDate(value) { return value ? value.slice(0,10).split('-').reverse().join('.') : ''; }
function luvrHistoryLabel(kind, item) {
    if (kind === 'movements') return `${luvrLocalDate(item.event_datetime)} ${item.event_datetime.slice(11,19)} · ${item.movement_type === 'ARRIVAL' ? 'Заезд' : 'Выезд'} · ${item.transport_type === 'SELF' ? 'Самостоятельно' : 'ЖД'}${item.source_file ? ' · '+item.source_file : ''}`;
    if (kind === 'sick-periods' && !item.date_to) return `Болеет с ${luvrLocalDate(item.date_from)}`;
    return `${luvrLocalDate(item.date_from)} — ${luvrLocalDate(item.date_to)}${kind === 'duration-exceptions' ? ' · '+(item.exception_type === 'SHIFT' ? 'Продление вахты' : 'Продление межвахты') : ''}`;
}

class LuvrHistoryController {
    constructor(request, render, error) { this.request=request; this.render=render; this.error=error; this.epoch=0; this.employeeId=null; this.items={}; this.busy=false; }
    open(employeeId) { this.epoch++; this.employeeId=employeeId; this.items={}; this.busy=false; this.render(this); }
    async load() {
        if (!this.employeeId || this.busy) return;
        const epoch=this.epoch, employee=this.employeeId;
        this.busy=true;this.render(this);
        try {
            const entries=await Promise.all(LUVR_HISTORY_KINDS.map(async kind=>[kind,(await this.request(`/api/employees/${employee}/luvr/${kind}`)).items]));
            if (epoch===this.epoch) this.items=Object.fromEntries(entries);
        } catch(error) { if(epoch===this.epoch)this.error(error.message); }
        finally { if(epoch===this.epoch){this.busy=false;this.render(this);} }
    }
    async mutate(kind, method, payload, itemId=null, deleteTicket=false) {
        if (!this.employeeId || this.busy) return false;
        const epoch=this.epoch, employee=this.employeeId;
        this.busy=true;
        try {
            const result=await this.request(`/api/employees/${employee}/luvr/${kind}${itemId ? '/'+itemId : ''}${deleteTicket?'?delete_ticket=true':''}`,method,payload);
            if(result?.ticket_id&&typeof document!=='undefined')document.dispatchEvent(new CustomEvent('luvr-rail-deleted',{detail:{employee_id:employee,movement_id:itemId,ticket_id:result.ticket_id}}));
            if(epoch!==this.epoch)return false;
            this.busy=false;await this.load();return true;
        } catch(error) { if(epoch===this.epoch)this.error(error.message);return false; }
        finally { if(epoch===this.epoch)this.busy=false; }
    }
}

async function luvrHistoryRequest(url, method='GET', payload) {
    const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(payload ? {body:JSON.stringify(payload)} : {})});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(data?.message || 'Не удалось выполнить операцию с историей сотрудника');
    return data;
}

let employeeLuvrController;
let railDeletePending=false;
function confirmRailMovementDelete(){
    if(railDeletePending)return Promise.resolve(false);
    railDeletePending=true;
    const modal=document.getElementById('railDeleteModal');modal.hidden=false;
    const previous=document.activeElement;
    return new Promise(resolve=>{
        const finish=accepted=>{modal.hidden=true;railDeletePending=false;document.removeEventListener('keydown',escape);previous?.focus();resolve(accepted);};
        const escape=event=>{if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();finish(false);}};
        document.getElementById('railDeleteCancel').onclick=()=>finish(false);
        document.getElementById('railDeleteClose').onclick=()=>finish(false);
        document.getElementById('railDeleteConfirm').onclick=()=>finish(true);
        document.addEventListener('keydown',escape);
        document.getElementById('railDeleteCancel').focus();
    });
}
function openEmployeeLuvrHistory(employeeId) {
    const block=document.getElementById('employeeLuvrHistory'), body=document.getElementById('employeeLuvrHistoryBody'), error=document.getElementById('employeeLuvrError');
    block.open=false;block.hidden=!employeeId;error.hidden=true;
    if(!employeeLuvrController){
        employeeLuvrController=new LuvrHistoryController(luvrHistoryRequest,state=>renderEmployeeLuvrHistory(body,state),message=>{error.textContent=message;error.hidden=false;});
        block.addEventListener('toggle',()=>{if(block.open && !Object.keys(employeeLuvrController.items).length)employeeLuvrController.load();});
    }
    employeeLuvrController.open(employeeId);
}

function renderEmployeeLuvrHistory(body, state) {
    body.replaceChildren();
    if(state.busy){body.textContent='Загрузка истории…';return;}
    const titles={'movements':'История перемещений','sick-periods':'Периоды болезни','duration-exceptions':'Согласованные исключения'};
    for(const kind of LUVR_HISTORY_KINDS){
        const section=document.createElement('section');section.className='luvr-history-section';section.dataset.kind=kind;
        const heading=document.createElement('h4');heading.textContent=titles[kind];section.append(heading);
        const add=document.createElement('button');add.type='button';add.className='secondary-button';add.textContent=kind==='movements'?'+ Добавить самостоятельный заезд/выезд':'+ Добавить';
        add.onclick=()=>editEmployeeLuvrRecord(section,kind,null,state);section.append(add);
        const list=document.createElement('div');list.className='luvr-history-list';section.append(list);
        for(const item of state.items[kind]||[]){
            const row=document.createElement('div');row.className='luvr-history-row';row.dataset.id=item.id;
            const label=document.createElement('div');label.textContent=luvrHistoryLabel(kind,item);row.append(label);
            const detail=document.createElement('small');detail.textContent=kind==='movements'?[item.departure_station,item.arrival_station].filter(Boolean).join(' → '):item.comment||'';row.append(detail);
            // RAIL is visible, but this stage's form edits SELF only.
            if(kind!=='movements'||item.transport_type==='SELF'){
                const edit=document.createElement('button');edit.type='button';edit.textContent='Редактировать';edit.onclick=()=>editEmployeeLuvrRecord(section,kind,item,state);row.append(edit);
            }
            const remove=document.createElement('button');remove.type='button';remove.textContent='Удалить';remove.onclick=async()=>{
                if(state.busy)return;
                const rail=kind==='movements'&&item.transport_type==='RAIL',epoch=state.epoch;
                remove.disabled=true;
                if(!(rail?await confirmRailMovementDelete():confirm('Удалить эту запись истории?'))||epoch!==state.epoch){remove.disabled=false;return;}
                document.getElementById('employeeLuvrError').hidden=true;
                await state.mutate(kind,'DELETE',null,item.id,rail);remove.disabled=false;
            };row.append(remove);list.append(row);
        }
        if(!list.children.length)list.textContent='Записей пока нет';
        body.append(section);
    }
}

function editEmployeeLuvrRecord(section, kind, item, state) {
    document.querySelectorAll('.luvr-history-editor').forEach(el=>el.remove());
    const form=document.createElement('form');form.className='luvr-history-editor';
    const field=(name,label,type='text',options=null)=>{
        const wrap=document.createElement('label');wrap.className='form-label';wrap.textContent=label;
        const input=document.createElement(options?'select':'input');input.name=name;
        if(options){for(const [value,text] of options){const o=document.createElement('option');o.value=value;o.textContent=text;input.append(o);}}
        else input.type=type;
        if(item?.[name]!=null)input.value=item[name];
        wrap.append(input);form.append(wrap);return input;
    };
    if(kind==='movements'){
        field('movement_type','Тип события','text',[['ARRIVAL','Заезд'],['DEPARTURE','Выезд']]);
        const mode=document.createElement('p');mode.textContent='Способ: Самостоятельно';form.append(mode);
        const date=field('date','Дата','date');date.required=true;date.value=item?.event_datetime?.slice(0,10)||'';
        const time=field('time','Время','time');time.required=true;time.step='0.000001';time.value=item?.event_datetime?.slice(11)||'';
        field('departure_station','Станция отправления (необязательно)');field('arrival_station','Станция прибытия (необязательно)');
    }else{
        if(kind==='duration-exceptions')field('exception_type','Тип','text',[['SHIFT','Продление вахты'],['OFF_SHIFT','Продление межвахты']]);
        field('date_from','Дата начала','date').required=true;
        field('date_to','Дата окончания','date').required=kind==='duration-exceptions';
        field('comment','Комментарий').required=kind==='duration-exceptions';
    }
    const save=document.createElement('button');save.type='submit';save.textContent='Сохранить';save.className='primary-button';form.append(save);
    const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Отмена';cancel.onclick=()=>form.remove();form.append(cancel);
    form.onsubmit=async event=>{
        event.preventDefault();if(state.busy)return;
        const error=document.getElementById('employeeLuvrError');error.hidden=true;
        try{
            const payload=luvrHistoryPayload(kind,Object.fromEntries(new FormData(form)));
            save.disabled=true;cancel.disabled=true;
            await state.mutate(kind,item?'PATCH':'POST',payload,item?.id);
        }catch(e){error.textContent=e.message;error.hidden=false;}
        finally{save.disabled=false;cancel.disabled=false;}
    };
    section.append(form);
}
if(typeof module!=='undefined')module.exports={luvrHistoryPayload,luvrLocalDate,luvrHistoryLabel,LuvrHistoryController,luvrHistoryRequest};
