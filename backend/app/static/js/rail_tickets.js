const RAIL_STATUS_LABELS={EMPLOYEE_NOT_FOUND:'Сотрудник не найден',ARCHIVED_EMPLOYEE:'Сотрудник находится в архиве',NEEDS_DIRECTION:'Выберите направление',READY:'Готов к подтверждению',CONFIRMED:'Событие сохранено',PARSE_ERROR:'Требует проверки',DUPLICATE:'Билет уже обработан',REJECTED:'Билет отклонён'};
function railEmployeeName(value){
    return (value||'').trim().split(/\s+/u).filter(Boolean).map(part=>part.charAt(0).toUpperCase()+part.slice(1).toLowerCase()).join(' ');
}
RAIL_STATUS_LABELS.UNSUPPORTED='Не является поддерживаемым билетом РЖД';
RAIL_STATUS_LABELS.NOT_LUVR_ROUTE='Не относится к ЛУВР — маршрут без станции Салым';
async function railDropFiles(dataTransfer){
    // Capture entries synchronously while the drop event still owns its data.
    const entries=Array.from(dataTransfer.items||[]).filter(x=>x.kind==='file').map(x=>x.webkitGetAsEntry?.());
    if(!entries.length||entries.some(x=>!x))return {files:Array.from(dataTransfer.files),errors:[]};
    const files=[],errors=[],stack=entries.slice();
    while(stack.length){
        const entry=stack.pop();
        try{
            if(entry.isFile)files.push(await new Promise((resolve,reject)=>entry.file(resolve,reject)));
            else if(entry.isDirectory){
                const reader=entry.createReader();
                while(true){const batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!batch.length)break;stack.push(...batch);}
            }
        }catch(e){errors.push('Не удалось прочитать элемент папки: '+entry.name);}
    }
    return {files,errors};
}
function railBatchStats(items,fileCount=items.length){
    const count=fn=>items.filter(fn).length;
    return {'Найдено файлов':fileCount,'Билетов РЖД (разобрано)':count(x=>['PARSED','CONFIRMED','REJECTED'].includes(x.status)&&!!x.full_name&&!!x.departure_datetime&&!!x.arrival_datetime),
        'Для ЛУВР (есть Салым)':count(x=>x.is_luvr_route===true),'Без станции Салым':count(x=>x.processing_status==='NOT_LUVR_ROUTE'),
        'Сотрудник не найден':count(x=>x.processing_status==='EMPLOYEE_NOT_FOUND'),'Требуют проверки':count(x=>['PARSE_ERROR','ARCHIVED_EMPLOYEE','NEEDS_DIRECTION'].includes(x.processing_status)),
        'Готовы к подтверждению':count(x=>x.processing_status==='READY'),'Дубликаты':count(x=>x.duplicate===true),
        'Ошибки парсинга':count(x=>x.processing_status==='PARSE_ERROR'),'Посторонние файлы':count(x=>x.processing_status==='UNSUPPORTED')};
}
function railDate(value){return value?value.slice(0,10).split('-').reverse().join('.')+' '+value.slice(11,16):'Не найдено';}
class RailTicketController{
    constructor(request,render,error){this.request=request;this.render=render;this.error=error;this.items=[];this.batchItems=[];this.pending=new Set();this.uploading=false;this.deletedIds=new Set();}
    removeDeletedTicket(id){this.deletedIds.add(id);this.items=this.items.filter(t=>t.id!==id);this.batchItems=this.batchItems.filter(t=>t.id!==id);this.render(this);}
    merge(items){for(const item of items){if(this.deletedIds.has(item.id))continue;const index=item.id?this.items.findIndex(x=>x.id===item.id):-1;if(index<0)this.items.push(item);else this.items[index]=item;}this.render(this);}
    async upload(files){
        if(this.uploading)return;
        const list=Array.from(files);if(!list.length)return;
        this.uploading=true;this.batchItems=[];this.fileCount=list.length;this.render(this);
        const batches=[];let batch=[],bytes=0;
        for(const file of list){const size=Math.min(file.size,10*1024*1024+1);if(batch.length&&(batch.length===50||bytes+size>50*1024*1024)){batches.push(batch);batch=[];bytes=0;}batch.push(file);bytes+=size;}if(batch.length)batches.push(batch);
        try{for(const files of batches){
            let items;
            try{const form=new FormData();for(const file of files)form.append('files',file,file.name);items=(await this.request('/api/rail-tickets/upload',{method:'POST',body:form})).items;}
            catch(e){this.error(e.message);items=files.map(file=>({source_filename:file.name,processing_status:'PARSE_ERROR',parse_errors:['Не удалось загрузить файл. Повторите загрузку.']}));}
            this.batchItems.push(...items.filter(t=>!this.deletedIds.has(t.id)));this.merge(items);
        }}finally{this.uploading=false;this.render(this);}
    }
    async action(id,operation,value){
        if(this.pending.has(id))return;
        this.pending.add(id);this.render(this);
        try{
            const url=`/api/rail-tickets/${id}${operation==='refresh'?'':'/'+operation}`;
            const options=operation==='refresh'?{}:{method:operation==='direction'?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(operation==='direction'?{movement_type:value}:{})};
            const item=(await this.request(url,options)).item;
            this.batchItems=this.batchItems.map(old=>old.id===item.id?{...item,duplicate:old.duplicate}:old);
            this.merge([item]);
        }catch(e){this.error(e.message);}
        finally{this.pending.delete(id);this.render(this);}
    }
}
async function railRequest(url,options={}){
    const response=await fetch(url,options),body=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(body?.message||'Не удалось выполнить операцию с билетом');
    return body;
}
function initRailTickets(){
    const page=document.getElementById('railTicketsPage'),list=document.getElementById('railTicketList'),error=document.getElementById('railTicketError');
    if(!page)return;
    const controller=new RailTicketController(railRequest,render,message=>{error.textContent=message;error.hidden=false;});
    let createTicketId=null;
    function render(state){
        list.replaceChildren();document.getElementById('railUploadProgress').hidden=!state.uploading;
        const summary=document.getElementById('railBatchSummary');summary.textContent=state.batchItems.length?Object.entries(railBatchStats(state.batchItems,state.fileCount)).map(([label,n])=>`${label}: ${n}`).join(' · '):'';
        document.querySelectorAll('[data-rail-upload]').forEach(button=>button.disabled=state.uploading);
        for(const item of state.items){
            const card=document.createElement('article');card.className='rail-ticket-card';if(item.id)card.dataset.ticketId=item.id;
            const line=(label,value)=>{const p=document.createElement('p');const strong=document.createElement('strong');strong.textContent=label+': ';p.append(strong,document.createTextNode(value||'Не найдено'));card.append(p);};
            line('Файл',item.source_filename);if(item.source_page)line('Страница',String(item.source_page));line('ФИО из билета',item.full_name);
            line('Отправление',`${item.departure_station||'Не найдено'} · ${railDate(item.departure_datetime)}`);
            line('Прибытие',`${item.arrival_station||'Не найдено'} · ${railDate(item.arrival_datetime)}`);
            if(!['UNSUPPORTED','NOT_LUVR_ROUTE'].includes(item.processing_status))line('Сопоставление',item.match_status==='FOUND'?`НАЙДЕН — ${item.employee_name}`:'Сотрудник не найден');
            line('Статус',RAIL_STATUS_LABELS[item.processing_status]);
            if(item.match_ambiguous)line('Проверка','Найдено несколько сотрудников с одинаковым ФИО. Требуется проверка справочника.');
            for(const message of item.parse_errors||[])line('Проверка',message);
            if(item.movement)line('Сохранённое событие',`${item.movement.movement_type==='ARRIVAL'?'Заезд':'Выезд'} · ${railDate(item.movement.event_datetime)} · №${item.movement.id}`);
            const buttons=document.createElement('div');buttons.className='rail-ticket-actions';card.append(buttons);
            const action=(label,operation,fn)=>{const b=document.createElement('button');b.type='button';b.className='secondary-button';b.textContent=label;b.dataset.action=operation;b.disabled=state.pending.has(item.id);b.onclick=()=>{error.hidden=true;fn();};buttons.append(b);};
            if(item.movement_type&&!item.movement)line('Направление',item.movement_type==='ARRIVAL'?'Заезд':'Выезд');
            if(item.processing_status==='READY')action('Подтвердить','confirm',()=>controller.action(item.id,'confirm'));
            if(item.processing_status==='EMPLOYEE_NOT_FOUND'&&!item.match_ambiguous){
                action('Создать сотрудника','create-employee',async()=>{createTicketId=item.id;await openEmployeeModal();document.getElementById('employeeNameInput').value=railEmployeeName(item.full_name);});
            }
            if(item.processing_status==='ARCHIVED_EMPLOYEE')line('Действие','Восстановление возможно только отдельным действием во вкладке «Сотрудники». После этого нажмите «Проверить сотрудника».');
            if(['EMPLOYEE_NOT_FOUND','ARCHIVED_EMPLOYEE','NEEDS_DIRECTION','READY'].includes(item.processing_status))action('Проверить сотрудника','refresh',()=>controller.action(item.id,'refresh'));
            if(item.id&&!['CONFIRMED','DUPLICATE','REJECTED','NOT_LUVR_ROUTE','UNSUPPORTED'].includes(item.processing_status))action('Отклонить','reject',()=>controller.action(item.id,'reject'));
            list.append(card);
        }
    }
    document.getElementById('railTicketsNavButton').addEventListener('click',()=>showMainSection(page,document.getElementById('railTicketsNavButton')));
    const files=document.getElementById('railTicketFiles'),folder=document.getElementById('railTicketFolder'),drop=document.getElementById('railTicketDrop');
    document.getElementById('railChooseFiles').onclick=()=>files.click();document.getElementById('railChooseFolder').onclick=()=>folder.click();
    for(const input of [files,folder])input.onchange=()=>{error.hidden=true;controller.upload(input.files);input.value='';};
    let collecting=false;
    for(const event of ['dragover','drop'])drop.addEventListener(event,async e=>{e.preventDefault();if(event==='drop'){
        drop.classList.remove('dragover');if(collecting||controller.uploading)return;collecting=true;error.hidden=true;
        try{const result=await railDropFiles(e.dataTransfer);await controller.upload(result.files);if(result.errors.length){error.textContent=result.errors.join('; ');error.hidden=false;}}
        finally{collecting=false;}
    }else drop.classList.add('dragover');});
    drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));
    document.addEventListener('employee-saved',()=>{if(createTicketId){const id=createTicketId;createTicketId=null;controller.action(id,'refresh');}});
    document.addEventListener('luvr-rail-deleted',event=>{controller.removeDeletedTicket(event.detail.ticket_id);if(createTicketId===event.detail.ticket_id)createTicketId=null;});
    // Cancelling employee creation leaves the parsed ticket intact.
    return controller;
}
if(typeof document!=='undefined')initRailTickets();
if(typeof module!=='undefined')module.exports={RailTicketController,railDate,RAIL_STATUS_LABELS,railDropFiles,railBatchStats,railEmployeeName};
