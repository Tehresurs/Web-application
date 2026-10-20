/* Display only: calendar values, shares, totals and checks come from the API. */
const PM_MODES={INSPECTION:'Инспекционный',OPERATIONAL:'Операционный',GEODETIC:'Геодезический контроль',CAMERAL:'Камеральный контроль'};
const PM_STATUS={OK:'Совпадает',WARNING:'Предупреждение',CONFLICT:'Конфликт'};
const PM_WARNINGS={ASSIGNMENT_UNKNOWN:'Назначение неизвестно',ASSIGNMENT_INCOMPLETE:'Не заполнены ПО, категория или режим',
    UNALLOCATED_WORK_TIME:'Рабочее время не распределено',FACT_ON_NONWORK_DAY:'Подтверждённый факт на нерабочий день',
    FACT_OUTSIDE_KNOWN_PERIOD:'Факт вне достоверного периода назначения',OVERLAPPING_ASSIGNMENT_PERIODS:'Пересекаются периоды назначений',
    LUVR_NEEDS_REVIEW:'Данные ЛУВР требуют проверки',LUVR_UNKNOWN:'Состояние ЛУВР неизвестно',LUVR_WARNINGS:'Есть предупреждения ЛУВР',OVER_ALLOCATION:'Превышено доступное время'};
const PM_SOURCE_ISSUES={AMBIGUOUS_MOVEMENTS:'Несколько перемещений в одну дату — заезд неоднозначен',ARRIVAL_UNCONFIRMED:'ЖД-заезд не связан с подтверждённым билетом',ARRIVAL_MISSING:'Исходный заезд отсутствует',ARRIVAL_CHANGED:'Данные исходного заезда изменились',SOURCE_TICKET_INACTIVE:'Билет аннулирован или не подтверждён',SOURCE_TICKET_CHANGED:'Данные исходного билета изменились',OUTSIDE_PERIOD:'Назначение выходит за границы периода'};
function pmCheckReasons(check){return (check.warnings||[]).map(code=>PM_WARNINGS[code]||code).join('; ');}
const pmAmount=value=>Number.isFinite(value)?(value/100).toFixed(2).replace('.',','):'—';
function pmCategories(items){const result=[],seen=new Set();const visit=rows=>{for(const row of rows||[]){if(!seen.has(row.id)){seen.add(row.id);result.push(row);}visit(row.children);}};visit(items);return result;}
function pmPayload(cell,field,value){
    const target=cell?.edit_target;
    if(!target||!['CATEGORY','CONTROL_MODE','PO'].includes(field))throw Error('Эта ячейка недоступна для редактирования');
    if(field==='CONTROL_MODE'&&!(cell.allowed_control_modes||['INSPECTION','OPERATIONAL']).includes(value))throw Error('Выберите режим контроля');
    if(['CATEGORY','PO'].includes(field)&&(!Number.isInteger(Number(value))||Number(value)<=0))throw Error(field==='PO'?'Выберите ПО':'Выберите категорию');
    const {fields,...identity}=target;
    return {...identity,field_name:field,version:fields[field].version,
        [field==='CATEGORY'?'category_id':field==='PO'?'po_id':'control_mode']:field==='CONTROL_MODE'?value:Number(value)};
}
class ProductionMatrixController {
    constructor(request,render,error,employeeId=null){Object.assign(this,{request,render,error,employeeId,epoch:0,busy:false,data:null,categories:[],pos:[],selection:null});}
    async load(year,month){
        const epoch=++this.epoch;year=Number(year);month=Number(month);
        this.data=null;this.selection=null;
        if(!Number.isInteger(year)||year<1900||year>9999||!Number.isInteger(month)||month<1||month>12){this.error('Выберите месяц от 1900 до 9999 года');this.busy=false;this.render(this);return;}
        this.selection={year,month};this.busy=true;this.render(this);
        try{const [matrix,categories,pos]=await Promise.all([this.request(`/api/production-matrix?year=${year}&month=${month}${this.employeeId?'&employee_id='+this.employeeId:''}`),this.request('/api/object-categories'),this.request('/api/po-types')]);
            if(epoch===this.epoch){this.data=matrix.item;this.categories=pmCategories(categories.items);this.pos=pos.items||[];}
        }catch(e){if(epoch===this.epoch)this.error(e.message);}
        finally{if(epoch===this.epoch){this.busy=false;this.render(this);}}
    }
    async change(cell,field,value){
        if(this.busy||!this.selection)return false;
        let payload;try{payload=pmPayload(cell,field,value);}catch(e){this.error(e.message);return false;}
        const epoch=this.epoch,{year,month}=this.selection;this.busy=true;this.render(this);
        let saved=false;
        try{await this.request(`/api/employees/${cell.employee_id}/production-matrix-overrides`,'PATCH',payload);saved=true;}
        catch(e){if(epoch===this.epoch)this.error(e.message);}
        try{if(epoch===this.epoch){const result=await this.request(`/api/production-matrix?year=${year}&month=${month}${this.employeeId?'&employee_id='+this.employeeId:''}`);if(epoch===this.epoch)this.data=result.item;}}
        catch(e){if(epoch===this.epoch){this.data=null;this.error('Не удалось обновить матрицу: '+e.message);}}
        finally{if(epoch===this.epoch){this.busy=false;this.render(this);}}
        return saved;
    }
}
function initProductionMatrix(options={}){
    const page=options.root||document.getElementById('productionMatrixPage');if(!page)return;
    const $=id=>options.root?page.querySelector(`[data-pm-id="${id}"]`):document.getElementById(id);
    const table=$('pmTable'),details=$('pmDetails'),scroll=$('pmScroll'),input=$('pmMonth');
    const expanded=new Set();let selected=null;
    const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
    const button=(text,fn,cls)=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
    const controller=new ProductionMatrixController(luvrHistoryRequest,render,message=>{$('pmError').textContent=message;$('pmError').hidden=false;},options.employeeId);
    const now=new Date();input.value=options.month||`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
    const load=()=>{options.onMonthChange?.(input.value);selected=null;$('pmError').hidden=true;const [year,month]=input.value.split('-');return controller.load(year,month);};
    input.onchange=load;$('pmRefresh').onclick=load;
    const expandAll=$('pmExpandAll');
    if(expandAll){
        expandAll.hidden=Boolean(options.employeeId);
        expandAll.onclick=()=>{
            const employees=controller.data?.employees||[];
            if(controller.busy||!controller.data?.formed||!employees.length)return;
            const collapse=employees.every(e=>expanded.has(e.employee_id));
            for(const employee of employees){if(collapse)expanded.delete(employee.employee_id);else expanded.add(employee.employee_id);}
            if(collapse)selected=null;
            render(controller);
        };
    }
    for(const [id,step] of [['pmPrevious',-1],['pmNext',1]])$(id).onclick=()=>{const [y,m]=input.value.split('-').map(Number);const date=new Date(y,m-1+step,1);if(date.getFullYear()<1900||date.getFullYear()>9999)return;input.value=`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}`;load();};
    if(!options.root)$('productionMatrixNavButton').onclick=()=>{showMainSection(page,$('productionMatrixNavButton'));load();};
    $('pmOpenLuvr').onclick=()=>document.getElementById('luvrMonthNavButton').click();
    $('pmOpenReports').onclick=()=>document.getElementById('processingNavButton').click();
    const choose=(employee,date,rowKey=null)=>{selected={employeeId:employee.employee_id,date,rowKey};expanded.add(employee.employee_id);render(controller);};
    function editor(employee,row,field){
        const cell=selected?.employeeId===employee.employee_id&&selected.rowKey===row.row_key?row.cells[selected.date]:null;
        const label=c=>field==='CATEGORY'?(c.category_name||'Не выбрана'):field==='PO'?(c.po_name||'Не выбрано'):(PM_MODES[c.control_mode]||'Не выбран');
        const title=field==='CATEGORY'?'Категория':field==='PO'?'ПО':'Режим контроля';
        const values=[...new Set(Object.values(row.cells).map(label))];
        if(!cell){const editable=Object.values(row.cells).find(c=>c.edit_target);const b=button(values.length===1?values[0]:'Меняется по датам',()=>choose(employee,editable?.date||Object.keys(row.cells)[0],row.row_key),'pm-chip');b.title='Нажмите для выбора: '+title;b.disabled=controller.busy||!editable;return b;}
        if(!cell.edit_target)return el('span',label(cell),'pm-chip');
        const select=el('select');select.dataset.field=field;select.setAttribute('aria-label',`${title} на ${cell.date}`);
        select.append(new Option('Выберите…',''));
        const choices=field==='CATEGORY'?controller.categories.map(c=>[c.id,c.name]):field==='PO'?controller.pos.map(c=>[c.id,c.name]):Object.entries(PM_MODES).filter(([code])=>(cell.allowed_control_modes||['INSPECTION','OPERATIONAL']).includes(code));
        for(const [value,text] of choices)select.append(new Option(text,value));
        const current=field==='CATEGORY'?cell.category_id:field==='PO'?cell.po_id:cell.control_mode;
        if(current&&!choices.some(([value])=>String(value)===String(current))){const historical=new Option(label(cell),current);historical.disabled=true;select.append(historical);}
        select.value=current||'';select.disabled=controller.busy;
        select.onchange=()=>{if(select.value){$('pmError').hidden=true;controller.change(cell,field,select.value);}};
        const wrap=el('div',null,'pm-editor');wrap.append(select,el('small',`${cell.source==='FACT'?'Факт':'С даты'} ${cell.date.split('-').reverse().join('.')}`));return wrap;
    }
    function footer(target,checks,labelColumns,totals){
        for(const [label,key] of [['Итого по объектам','object_cents'],['Камеральное время','cameral_cents'],['ЛУВР (доступное время)','available_cents'],['Проверка',null]]){
            const tr=el('tr',null,'pm-total');const title=el('th',label);title.colSpan=labelColumns;tr.append(title);
            for(const check of checks){const td=el('td',key?pmAmount(check[key]):({OK:'✓',WARNING:'!',CONFLICT:'×'}[check.status]),'pm-check-'+check.status);
                td.title=key?label:`${PM_STATUS[check.status]}: объекты ${pmAmount(check.object_cents)} + камерально ${pmAmount(check.cameral_cents)} / ЛУВР ${pmAmount(check.available_cents)}${check.dk_cents?' · ДК '+pmAmount(check.dk_cents)+' (непроизводственное время)':''}${pmCheckReasons(check)?' · '+pmCheckReasons(check):''}`;tr.append(td);}
            const total=el('td',key?pmAmount(totals[key]):`! ${totals.warning_days} / × ${totals.conflict_days}`);total.colSpan=labelColumns===2?2:1;tr.append(total);target.append(tr);
        }
    }
    function nested(employee,dates){
        const wrap=el('div',null,'pm-inner-scroll'),t=el('table',null,'pm-inner');wrap.dataset.employee=employee.employee_id;const head=el('thead'),hr=el('tr');
        const widths=[90,170,100,110,90,...dates.map(()=>62),160],cols=el('colgroup');
        for(const width of widths){const col=el('col');col.style.width=width+'px';cols.append(col);}t.append(cols);t.style.width=widths.reduce((sum,width)=>sum+width,0)+'px';
        for(const label of ['ПО','Объект / подобъект','Категория','Режим контроля','Субподрядчик',...dates.map(d=>d.slice(-2)),'Итого'])hr.append(el('th',label));
        head.append(hr);t.append(head);const body=el('tbody');
        for(const row of employee.rows){const tr=el('tr',null,row.kind==='CAMERAL'?'pm-cameral':'');tr.dataset.rowKey=row.row_key;const first=Object.values(row.cells)[0];
            const poCell=el('td');poCell.append(editor(employee,row,'PO'));tr.append(poCell,el('td',row.kind==='CAMERAL'?'Камеральная работа':[first.object_name,first.subobject_name].filter(Boolean).join(' / ')));
            for(const field of ['CATEGORY','CONTROL_MODE']){const td=el('td');td.append(editor(employee,row,field));tr.append(td);}
            tr.append(el('td',first.subcontractor_name||'—'));
            for(const day of dates){const td=el('td'),cell=row.cells[day];if(cell){const b=button(cell.is_dk?'0 ДК':`${pmAmount(cell.share_cents)} ${cell.source==='FACT'?'Ф':'Пл'}`,()=>choose(employee,day,row.row_key),`pm-cell pm-source-${cell.source} pm-check-${cell.status}${cell.is_dk?' pm-dk':''}`);b.dataset.date=day;b.title=`${day} · ${cell.source==='FACT'?'Подтверждённый факт':'План'} · ${PM_STATUS[cell.status]}${cell.is_dk?' · Проведен ДК':''}`;b.setAttribute('aria-pressed',String(selected?.rowKey===row.row_key&&selected.date===day));td.append(b);}else td.textContent='—';tr.append(td);}
            tr.append(el('td',pmAmount(row.total_cents)));body.append(tr);
        }
        if(!employee.rows.length){const tr=el('tr'),td=el('td','Нет производственных строк. Выберите день для просмотра причины.');td.colSpan=dates.length+6;tr.append(td);body.append(tr);}
        t.append(body);const foot=el('tfoot');footer(foot,employee.checks,5,employee.totals);t.append(foot);wrap.append(t);return wrap;
    }
    function render(state){
        const left=scroll.scrollLeft,top=scroll.scrollTop;table.replaceChildren();details.hidden=true;
        $('pmStatus').textContent=state.busy?'Загрузка…':!state.data?'Матрица не загружена':!state.data.formed?'Сначала сформируйте выбранный месяц в ЛУВР':state.data.employees.length?`Сотрудников: ${state.data.employees.length}. Выберите день; ПО, категорию и режим можно изменить в раскрытой строке.`:'В месяце нет сотрудников';
        $('pmRefresh').disabled=state.busy;
        if(expandAll){
            const employees=state.data?.employees||[];
            const allExpanded=employees.length>0&&employees.every(e=>expanded.has(e.employee_id));
            expandAll.disabled=state.busy||!state.data?.formed||!employees.length;
            expandAll.textContent=allExpanded?'Свернуть все строки':'Развернуть все строки';
            expandAll.setAttribute('aria-expanded',String(allExpanded));
        }
        if(options.employeeId&&state.data?.formed&&!state.data.employees.length)$('pmStatus').textContent='Сотрудник не включён в ЛУВР выбранного месяца. Производственная матрица строится по составу ЛУВР.';
        if(!state.data||!state.data.formed||!state.data.employees.length)return;
        if(options.employeeId)expanded.add(options.employeeId);
        const dates=state.data.day_totals.map(d=>d.date);
        const colgroup=el('colgroup');for(const width of [42,518,...dates.map(()=>62),75,85]){const c=el('col');c.style.width=width+'px';colgroup.append(c);}table.append(colgroup);table.style.width=(560+dates.length*62+160)+'px';
        const head=el('thead'),hr=el('tr');for(const label of ['№','Сотрудник / Должность',...dates.map(d=>d.slice(-2)),'Раб. дней','Раб. время'])hr.append(el('th',label));head.append(hr);table.append(head);
        const body=el('tbody');state.data.employees.forEach((employee,index)=>{
            const tr=el('tr',null,'pm-employee');tr.dataset.employee=employee.employee_id;tr.append(el('td',index+1));const name=el('td',null,'pm-name');
            const toggle=button(`${expanded.has(employee.employee_id)?'▾':'▸'} ${employee.full_name}`,()=>{expanded.has(employee.employee_id)?expanded.delete(employee.employee_id):expanded.add(employee.employee_id);render(state);});
            toggle.setAttribute('aria-expanded',String(expanded.has(employee.employee_id)));name.append(toggle,el('small',employee.position_name||'Должность не указана'));tr.append(name);
            for(const day of employee.luvr_days){const td=el('td');const b=button(employee.dk_dates?.includes(day.date)?'0 ДК':day.final_display||'—',()=>choose(employee,day.date),`pm-cell pm-state-${day.final_code}${employee.dk_dates?.includes(day.date)?' pm-dk':''}`);b.title=`${employee.full_name} · ${day.date} · ${day.final_display||'Нет рабочего времени'}${employee.dk_dates?.includes(day.date)?' · Проведен ДК':''}`;b.dataset.date=day.date;td.append(b);tr.append(td);}
            tr.append(el('td',employee.totals.working_days),el('td',pmAmount(employee.totals.available_cents)));body.append(tr);
            if(expanded.has(employee.employee_id)){const expandedRow=el('tr',null,'pm-expanded'),td=el('td');td.colSpan=dates.length+4;td.append(nested(employee,dates));expandedRow.append(td);body.append(expandedRow);}
        });table.append(body);const foot=el('tfoot');footer(foot,state.data.day_totals,2,state.data.totals);table.append(foot);
        scroll.scrollLeft=left;scroll.scrollTop=top;renderDetails(state);
    }
    function renderDetails(state){
        details.replaceChildren();if(!selected)return;
        const employee=state.data?.employees.find(e=>e.employee_id===selected.employeeId);if(!employee)return;
        const day=employee.luvr_days.find(d=>d.date===selected.date),check=employee.checks.find(d=>d.date===selected.date);if(!day||!check)return;
        details.hidden=false;const heading=el('div',null,'pm-detail-heading');heading.append(el('h3','Детали дня'),button('×',()=>{selected=null;render(state);},'pm-close'));details.append(heading);
        details.append(el('strong',employee.full_name),el('p',`${selected.date.split('-').reverse().join('.')} · ${check.position_name||employee.position_name||'—'}`),
            el('p',`ЛУВР: ${day.final_display||'Нет рабочего времени'} · Доступно: ${pmAmount(check.available_cents)}`),el('p',PM_STATUS[check.status],'pm-check-'+check.status));
        if(check.is_dk)details.append(el('p','0 ДК · Проведен ДК','pm-dk pm-dk-note'));
        if(employee.dk_eligible_position && state.data.capabilities?.can_manage_dk){
            const action=button(check.is_dk?'Отменить ДК':'Назначить ДК',async()=>{
                if(controller.busy)return;
                action.disabled=true;$('pmError').hidden=true;
                try{
                    await luvrHistoryRequest('/api/employees/'+employee.employee_id+'/production-matrix/dk/'+selected.date,check.is_dk?'DELETE':'PUT');
                    await load();document.dispatchEvent(new CustomEvent('matrix-dk-changed'));
                }catch(e){$('pmError').textContent=e.message;$('pmError').hidden=false;action.disabled=false;}
            },'secondary-button');
            action.disabled=controller.busy||(!check.is_dk&&!['FULL','HALF'].includes(day.final_code));
            if(action.disabled)action.title='ДК разрешён только при ЛУВР 1 или 0,5';
            details.append(action);
        }
        for(const warning of check.warnings)details.append(el('p',PM_WARNINGS[warning]||warning,'pm-warning'));

        for(const warning of day.warnings||[])details.append(el('p',warning.message||warning.code,'pm-warning'));
        if(check.warnings.includes('FACT_OUTSIDE_KNOWN_PERIOD')){
            const sources=(employee.source_warnings||[]).filter(w=>w.code!=='FACT_OUTSIDE_KNOWN_PERIOD');
            for(const warning of sources){
                const ids=warning.movement_ids?.length?warning.movement_ids:warning.movement_id?[warning.movement_id]:[];
                details.append(el('p',(PM_SOURCE_ISSUES[warning.code]||warning.code)+(warning.date?' · '+warning.date:'')+(ids.length?' · Перемещения № '+ids.join(', '):''),'pm-warning'));
            }
        }

        const cells=employee.rows.map(r=>({row:r,cell:r.cells[selected.date]})).filter(x=>x.cell);
        if(!cells.length)details.append(el('p',check.available_cents?'Назначение неизвестно или отсутствует.':'На эту дату производственных строк нет.'));
        for(const {row,cell} of cells){const card=el('section',null,'pm-detail-card');card.append(el('strong',cell.source==='FACT'?'Подтверждённый факт':'План'),el('p',cell.kind==='CAMERAL'?'Камеральный контроль':[cell.po_name,cell.object_name,cell.subobject_name].filter(Boolean).join(' → ')),
            el('p',`Категория: ${cell.category_name||'—'}`),el('p',`Режим: ${PM_MODES[cell.control_mode]||'Не выбран'}`),el('p',`Субподрядчик: ${cell.subcontractor_name||'—'}`),el('p',cell.is_dk?'0 ДК · Проведен ДК':`Доля времени: ${pmAmount(cell.share_cents)}`));
            if(cell.source==='FACT' && cell.luvr_final_code==='TRAVEL')card.append(el('p','Отчёт сохранён в истории, но к учёту не принят: в ЛУВР «Д», рабочее время 0.','pm-note'));
            if(cell.source==='FACT' && cell.source_fact_id)card.append(button('Проверить источник',()=>matrixReportSource(cell,card),'secondary-button'));
            if(cell.source==='FACT' && cell.source_fact_id)card.append(button('Удалить событие за этот день',()=>matrixReportDelete(cell,card),'secondary-button'));
            if(cell.source_file)card.append(el('small',`Основание: ${cell.source_file}`));
            if(cell.basis_kind==='POSITION_RULE')card.append(el('small','По настройке должности: ежедневный отчёт не требуется.'));
            if(cell.edit_target)card.append(button('Выбрать строку для изменения',()=>choose(employee,selected.date,row.row_key),'secondary-button'));
            details.append(card);
        }
    }
    if(!options.root)for(const event of ['luvr-ticket-state-changed','luvr-rail-deleted','employee-saved','daily-control-fact-saved','matrix-dk-changed'])document.addEventListener(event,()=>{if(!page.hidden)load();else controller.data=null;});
    if(!options.root)document.addEventListener('matrix-report-open',async event=>{
        const context=event.detail;input.value=context.date.slice(0,7);await load();
        const employee=controller.data?.employees.find(e=>e.employee_id===Number(context.employee_id));
        if(!employee){$('pmError').textContent='Сотрудник не включён в ЛУВР выбранного месяца.';$('pmError').hidden=false;return;}
        const row=employee.rows.find(r=>r.cells[context.date]);choose(employee,context.date,row?.row_key);
        table.querySelector('[data-employee="'+employee.employee_id+'"]')?.scrollIntoView({block:'nearest'});
    });
    if(options.root)load();
    return {load,controller};
}
if(typeof document!=='undefined')initProductionMatrix();
if(typeof module!=='undefined')module.exports={ProductionMatrixController,pmPayload,pmCategories,pmAmount,pmCheckReasons};
