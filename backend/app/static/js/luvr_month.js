/* Membership is persistent; all day values and totals are calculated by the backend. */
class LuvrMonthController {
    constructor(request, render, error) {Object.assign(this,{request,render,error,epoch:0,busy:false,data:null,selection:null});}
    async select(year,month,asOf='') {
        this.epoch++;this.data=null;this.busy=false;
        this.asOf=asOf;
        year=Number(year);month=Number(month);
        this.selection=Number.isInteger(year)&&year>=1&&year<=9999&&Number.isInteger(month)&&month>=1&&month<=12?{year,month}:null;
        this.render(this);if(this.selection)await this.load();
    }
    async load() {return this.run();}
    async run(url,method,payload) {
        if(this.busy||!this.selection)return false;
        const epoch=this.epoch,s=this.selection;this.busy=true;this.render(this);
        try {
            if(url)await this.request(url,method,payload);
            if(epoch!==this.epoch)return false;
            const result=await this.request(`/api/luvr/month?year=${s.year}&month=${s.month}${this.asOf?'&as_of_date='+encodeURIComponent(this.asOf):''}`);
            if(epoch!==this.epoch)return false;
            this.data=result.item;return true;
        } catch(e) {if(epoch===this.epoch)this.error(e.message);return false;}
        finally {if(epoch===this.epoch){this.busy=false;this.render(this);}}
    }
    form() {return this.run('/api/luvr/month/form','POST',this.selection);}
    add(employee) {return this.run('/api/luvr/month/employees','POST',{...this.selection,employee_id:Number(employee)});}
    remove(employee,confirmed) {
        if(!confirmed||!this.selection)return false;
        return this.run(`/api/luvr/month/employees/${employee}?year=${this.selection.year}&month=${this.selection.month}`,'DELETE');
    }
    change(employee,day,value,comment='',restore=false) {
        if(restore&&!day.override_id)return false;
        return this.run(`/api/employees/${employee}/luvr/day-overrides${restore?'/'+day.override_id:''}`,
            restore?'DELETE':'POST',restore?undefined:{work_date:day.date,value,comment:comment.trim()||null});
    }
}

function luvrMonthHeaders(year,month,count) {
    const weekdays=['Вс','Пн','Вт','Ср','Чт','Пт','Сб'];
    return Array.from({length:count},(_,i)=>{
        const date=new Date(0);date.setFullYear(year,month-1,i+1);date.setHours(12,0,0,0);
        return `${i+1} ${weekdays[date.getDay()]}`;
    });
}

function luvrExportPayload(selection,rows) {
    return {...selection,employee_ids:Array.from(rows,row=>Number(row.dataset.employee))};
}

function luvrMatchesDayFilters(employee,filters) {
    return Object.entries(filters).every(([date,value])=>{
        const actual=String(employee.days.find(day=>day.date===date)?.final_display??'');
        return value==='WORKING'?['1','0,5'].includes(actual):actual===value;
    });
}

function luvrSpecialtyMissing(employee) {return !(employee.specialty||'').trim();}

async function openLuvrEmployee(employeeId,request,open) {
    const result=await request('/api/employees?include_archived=true');
    const item=result.items.find(employee=>employee.id===Number(employeeId));
    if(!item)throw new Error('Сотрудник не найден. Обновите ЛУВР.');
    await open(item);
}

function initLuvrMonth() {
    const $=id=>document.getElementById(id),page=$('luvrMonthPage');if(!page)return;
    const year=$('luvrMonthYear'),month=$('luvrMonthNumber'),editor=$('luvrMonthEditor'),error=$('luvrMonthError');
    const value=$('luvrMonthValue'),comment=$('luvrMonthComment'),picker=$('luvrMonthEmployee');let editing=null;
    let sortField='full_name',sortDirection='asc',exporting=false,dayFilters={};
    const controller=new LuvrMonthController(luvrHistoryRequest,render,message=>{error.textContent=message;error.hidden=false;});
    const now=new Date();year.value=now.getFullYear();month.value=now.getMonth()+1;
    for(const [code,label] of Object.entries(LUVR_CALENDAR_VALUES))value.append(new Option(label,code));
    const close=()=>{editing=null;editor.hidden=true;$('luvrDurationDetails').hidden=true;};
    document.addEventListener('employee-saved',event=>{
        if(!controller.data?.employees.some(employee=>employee.employee_id===Number(event.detail?.id)))return;
        close();controller.epoch++;controller.busy=false;controller.load();
    });
    for(const eventName of ['luvr-rail-deleted','luvr-ticket-state-changed'])document.addEventListener(eventName,()=>{
        close();controller.epoch++;controller.busy=false;controller.data=null;
        controller.render(controller);if(controller.selection)controller.load();
    });
    const select=()=>{close();error.hidden=true;picker.hidden=true;return controller.select(year.value,month.value,$('luvrMonthAsOf').value);};
    const changePeriod=()=>{dayFilters={};$('luvrMonthAsOf').value='';return select();};
    year.onchange=changePeriod;month.onchange=changePeriod;$('luvrMonthAsOf').onchange=select;
    $('luvrDurationClose').onclick=()=>{$('luvrDurationDetails').hidden=true;};
    $('luvrMonthNavButton').onclick=()=>{showMainSection(page,$('luvrMonthNavButton'));select();};
    $('luvrMonthForm').onclick=()=>controller.form();
    $('luvrMonthExport').onclick=async()=>{
        if(!controller.data?.formed||controller.busy||exporting)return;
        const selected={...controller.selection},button=$('luvrMonthExport');button.disabled=true;exporting=true;error.hidden=true;
        const payload=luvrExportPayload(selected,$('luvrMonthBody').querySelectorAll('tr[data-employee]'));
        try {
            const response=await fetch('/api/luvr/month/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            if(!response.ok){const result=await response.json();throw new Error(result.message||'Не удалось выгрузить ЛУВР.');}
            const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
            link.href=url;link.download=`ЛУВР_${selected.year}-${String(selected.month).padStart(2,'0')}.xlsx`;
            document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
        }catch(e){error.textContent=e.message;error.hidden=false;}
        finally{exporting=false;button.disabled=controller.busy||!controller.data?.formed;}
    };
    $('luvrDayFiltersReset').onclick=()=>{dayFilters={};close();render(controller);};
    $('luvrMonthRefresh').onclick=()=>{close();error.hidden=true;controller.load();};
    $('luvrMonthAdd').onclick=async()=>{
        const epoch=controller.epoch;
        try {
            const groups=await Promise.all([luvrHistoryRequest('/api/employees'),luvrHistoryRequest('/api/employees?archived=true')]);
            if(epoch!==controller.epoch)return;
            const members=new Set(controller.data.employees.map(e=>e.employee_id));
            const employees=[...new Map(groups.flatMap(g=>g.items).map(e=>[e.id,e])).values()].filter(e=>!members.has(e.id));
            picker.replaceChildren(new Option('Выберите сотрудника для добавления',''));
            employees.sort((a,b)=>a.full_name.localeCompare(b.full_name,'ru')).forEach(e=>picker.append(new Option(e.full_name+(e.is_archived?' (архив)':''),e.id)));
            picker.hidden=false;picker.focus();
        }catch(e){error.textContent=e.message;error.hidden=false;}
    };
    picker.onchange=async()=>{if(picker.value&&await controller.add(picker.value))picker.hidden=true;};
    $('luvrMonthCancel').onclick=close;
    editor.onsubmit=async e=>{e.preventDefault();if(!editing)return;const target=editing;
        if(await controller.change(target.employee,target.day,value.value,comment.value)&&editing===target)close();};
    $('luvrMonthRestore').onclick=async()=>{if(!editing)return;const target=editing;
        if(await controller.change(target.employee,target.day,null,'',true)&&editing===target)close();};
    function edit(employee,day) {
        editing={employee:employee.employee_id,day};value.value=day.override_code||day.final_code;comment.value=day.override_comment||'';
        $('luvrMonthDetail').textContent=`${employee.full_name} · ${day.date} · Автоматически: ${day.auto_display||'пусто'} · Итог: ${day.final_display||'пусто'} · Причина: ${LUVR_SOURCES[day.source_type]||day.source_type} · ${LUVR_SOURCES[day.final_source_type]||''} · Изменено вручную: ${day.manually_changed?'да':'нет'}${day.is_sick?' · Период болезни':''}${day.warnings.map(w=>' · '+w.message).join('')}`;
        $('luvrMonthRestore').hidden=!day.override_id;editor.hidden=false;editor.scrollIntoView({block:'nearest'});value.focus();
    }
    function render(state) {
        for(const id of ['luvrMonthForm','luvrMonthRefresh','luvrMonthAdd','luvrMonthSave','luvrMonthRestore'])$(id).disabled=state.busy||!state.selection;
        picker.disabled=state.busy;
        $('luvrMonthExport').disabled=exporting||state.busy||!state.data?.formed;
        $('luvrMonthExport').title=state.data?.formed?'Выгрузить ЛУВР в Excel':'Сначала сформируйте ЛУВР за выбранный месяц';
        $('luvrMonthAdd').disabled=state.busy||!state.data?.formed;
        $('luvrMonthForm').hidden=!!state.data?.formed;
        $('luvrMonthInfo').textContent=(state.busy?'Обновление…':!state.data?'Выберите год и месяц':!state.data.formed?'Месяц ещё не сформирован':`Состав сохранён. Сотрудников: ${state.data.employees.length}`)+(state.data?` · Состояние на ${state.data.as_of_date}${state.data.is_projection?' · Прогноз по известной истории':''}`:'');
        $('luvrDayFiltersInfo').textContent='';$('luvrDayFiltersReset').hidden=!Object.keys(dayFilters).length;
        renderLuvrDayTotals($('luvrMonthTotals'),state.data);
        const head=$('luvrMonthHead'),body=$('luvrMonthBody');head.replaceChildren();body.replaceChildren();if(!state.data)return;
        const data=state.data,headers=['№','ФИО','Должность','№ НРС','Специальность','Место','График','Состояние',...luvrMonthHeaders(data.year,data.month,data.days_in_month),'Раб. дни','Д','МВ','П','Действия'];
        const sortColumns={1:'full_name',2:'position_name',4:'specialty',5:'work_location',6:'work_schedule',7:'current_state',
            [8+data.days_in_month]:'work_days_total',[9+data.days_in_month]:'travel_days_total',[10+data.days_in_month]:'off_shift_days_total',[11+data.days_in_month]:'downtime_days_total'};
        headers.forEach((text,i)=>{
            const th=document.createElement('th');if(i===1)th.className='luvr-name';
            const field=sortColumns[i];
            if(field){
                const button=document.createElement('button');button.type='button';button.className='luvr-sort-button';button.dataset.sort=field;
                button.textContent=text+(sortField===field?(sortDirection==='asc'?' ↑':' ↓'):'');button.disabled=state.busy;
                th.setAttribute('aria-sort',sortField===field?(sortDirection==='asc'?'ascending':'descending'):'none');
                button.onclick=()=>{
                    const scroll=page.querySelector('.luvr-month-scroll'),left=scroll.scrollLeft;
                    sortDirection=sortField===field&&sortDirection==='asc'?'desc':'asc';sortField=field;
                    render(controller);scroll.scrollLeft=left;
                };th.append(button);
            }else th.textContent=text;
            if(i>=8&&i<8+data.days_in_month){
                const date=`${data.year}-${String(data.month).padStart(2,'0')}-${String(i-7).padStart(2,'0')}`;
                const filter=document.createElement('select');filter.className='luvr-day-filter';filter.dataset.date=date;
                filter.setAttribute('aria-label',`Фильтр за ${date.split('-').reverse().join('.')}`);
                filter.append(new Option('Все','*'));
                const values=new Set(data.employees.map(e=>String(e.days.find(d=>d.date===date)?.final_display??'')));
                if(Object.hasOwn(dayFilters,date))values.add(dayFilters[date]);
                if(values.has('1')||values.has('0,5')||values.has('WORKING'))filter.append(new Option('1 + 0,5','WORKING'));
                for(const v of [...values].filter(v=>v!=='1'&&v!=='WORKING').sort((a,b)=>a.localeCompare(b,'ru',{numeric:true})))filter.append(new Option(v||'Пусто',v));
                filter.value=Object.hasOwn(dayFilters,date)?dayFilters[date]:'*';filter.disabled=state.busy;
                filter.classList.toggle('is-active',Object.hasOwn(dayFilters,date));
                filter.onchange=()=>{const scroll=page.querySelector('.luvr-month-scroll'),left=scroll.scrollLeft;
                    if(filter.value==='*')delete dayFilters[date];else dayFilters[date]=filter.value;
                    close();render(controller);scroll.scrollLeft=left;
                };th.append(filter);
            }
            head.append(th);
        });
        const count=data.employees.filter(e=>luvrMatchesDayFilters(e,dayFilters)).length;
        $('luvrDayFiltersInfo').textContent=Object.keys(dayFilters).length?`Показано ${count} из ${data.employees.length}. Итоги и Excel — по всему составу месяца.`:'';
        $('luvrDayFiltersReset').hidden=!Object.keys(dayFilters).length;
        sortLuvrEmployees(data.employees,sortField,sortDirection).forEach((employee,index)=>{
            const tr=document.createElement('tr');tr.dataset.employee=employee.employee_id;tr.hidden=!luvrMatchesDayFilters(employee,dayFilters);
            const cell=text=>{const td=document.createElement('td');td.textContent=text??'';tr.append(td);return td;};
            cell(index+1);
            const nameCell=cell('');nameCell.className='luvr-name';
            const nameButton=document.createElement('button');nameButton.type='button';nameButton.className='luvr-employee-link';nameButton.dataset.action='edit-employee';
            nameButton.textContent=employee.full_name+(employee.is_archived?' (архив)':'');nameButton.disabled=state.busy;
            nameButton.onclick=async()=>{const epoch=controller.epoch;nameButton.disabled=true;
                try{await openLuvrEmployee(employee.employee_id,luvrHistoryRequest,item=>epoch===controller.epoch?openEmployeeModal(item):undefined);}
                catch(e){error.textContent=e.message;error.hidden=false;}finally{nameButton.disabled=controller.busy;}};
            nameCell.append(nameButton);cell(employee.position_name);cell(employee.nrs_number);
            const specialty=cell(luvrSpecialtyMissing(employee)?'Не указана':employee.specialty);
            if(luvrSpecialtyMissing(employee)){specialty.className='luvr-specialty-error';specialty.title='Укажите специальность в связанной должности. Открыть сотрудника можно по ФИО.';}
            cell(({OBJECT:'Объект',OFFICE:'Офис'})[employee.work_location]||'');cell(({SHIFT:'Вахта',FIVE_TWO:'5/2'})[employee.work_schedule]||'');
            const status=employee.duration,statusCell=cell('');
            if(status.current_state!=='NOT_APPLICABLE'){
                const detail=document.createElement('button');detail.type='button';detail.dataset.action='duration-detail';
                detail.className='luvr-duration-status'+(status.indicator_enabled?' luvr-duration-'+status.indicator_status.toLowerCase():'');
                detail.textContent=luvrDurationSummary(status);detail.disabled=state.busy;
                detail.onclick=()=>{$('luvrDurationText').textContent=luvrDurationDetails(employee,data.is_projection);$('luvrDurationDetails').hidden=false;$('luvrDurationDetails').scrollIntoView({block:'nearest'});};
                statusCell.append(detail);
            }
            employee.days.forEach(day=>{
                const td=cell(''),button=document.createElement('button');button.type='button';button.textContent=day.final_display;button.dataset.date=day.date;
                luvrColorDay(td,day);button.className='luvr-month-day';button.disabled=state.busy;button.setAttribute('aria-label',`${day.date}: ${day.final_display||'пусто'}`);
                button.title=[day.is_sick?'Период болезни':LUVR_SOURCES[day.final_source_type],...day.warnings.map(w=>w.message)].filter(Boolean).join('. ');
                if(day.manually_changed)td.classList.add('luvr-day-manual');button.onclick=()=>edit(employee,day);td.append(button);
            });
            for(const key of ['work_days_total','travel_days_total','off_shift_days_total','downtime_days_total'])cell(String(employee.totals[key]).replace('.',',')).dataset.total=key;
            const remove=document.createElement('button');remove.type='button';remove.textContent='Убрать из месяца';remove.disabled=state.busy;remove.dataset.action='remove-member';
            remove.onclick=()=>{const accepted=confirm(`Убрать ${employee.full_name} из этого месяца? Сотрудник и его история сохранятся.`);if(accepted)close();controller.remove(employee.employee_id,accepted);};cell('').append(remove);body.append(tr);
        });
    }
    render(controller);return controller;
}
if(typeof document!=='undefined')initLuvrMonth();
if(typeof module!=='undefined')module.exports={LuvrMonthController,luvrMonthHeaders,luvrExportPayload,luvrSpecialtyMissing,openLuvrEmployee,luvrMatchesDayFilters};
