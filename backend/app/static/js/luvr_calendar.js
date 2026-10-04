const LUVR_CALENDAR_VALUES={FULL:'1',HALF:'0,5',TRAVEL:'Д',OFF_SHIFT:'МВ',DOWNTIME:'П',DISMISSED:'Уволен',EMPTY:'Пусто'};
const LUVR_SOURCES={STATE:'Состояние по истории',ARRIVAL:'Заезд',DEPARTURE:'Выезд',RAIL_TRAVEL:'Поездка к Салыму',OVERRIDE:'Ручная корректировка',SICK:'Период болезни',DISMISSAL:'Увольнение',UNKNOWN:'Нет подтверждённого состояния',WEEKDAY:'Рабочий день 5/2',WEEKEND:'Выходной 5/2'};
class LuvrCalendarController{
    constructor(request,render,error){this.request=request;this.render=render;this.error=error;this.epoch=0;this.data=null;this.busy=false;this.selection=null;}
    async select(employee,month){
        this.epoch++;this.data=null;this.busy=false;this.selection=null;
        if(employee&&/^\d{4}-\d{2}$/.test(month)){
            const [year,number]=month.split('-').map(Number);
            if(year>=1&&number>=1&&number<=12)this.selection={employee:Number(employee),year,month:number};
        }
        this.render(this);if(this.selection)await this.load();
    }
    async load(){
        if(!this.selection||this.busy)return;
        const epoch=this.epoch,s=this.selection;this.busy=true;this.render(this);
        try{const result=await this.request(`/api/employees/${s.employee}/luvr/calendar?year=${s.year}&month=${s.month}`);
            if(epoch===this.epoch)this.data=result.item;
        }catch(e){if(epoch===this.epoch){this.data=null;this.error(e.message);}}
        finally{if(epoch===this.epoch){this.busy=false;this.render(this);}}
    }
    async change(day,value,comment='',restore=false){
        if(this.busy||!this.data||!this.selection)return false;
        if(!restore&&!Object.hasOwn(LUVR_CALENDAR_VALUES,value)){this.error('Выберите значение дня');return false;}
        if(restore&&!day.override_id)return false;
        const epoch=this.epoch,employee=this.selection.employee;this.busy=true;this.render(this);
        try{
            await this.request(`/api/employees/${employee}/luvr/day-overrides${restore?'/'+day.override_id:''}`,
                restore?'DELETE':'POST',restore?undefined:{work_date:day.date,value,comment:comment.trim()||null});
            if(epoch!==this.epoch)return false;
            this.busy=false;await this.load();return true;
        }catch(e){if(epoch===this.epoch)this.error(e.message);return false;}
        finally{if(epoch===this.epoch){this.busy=false;this.render(this);}}
    }
}

function initLuvrCalendar(){
    const page=document.getElementById('luvrCalendarPage');if(!page)return;
    const employee=document.getElementById('luvrCalendarEmployee'),month=document.getElementById('luvrCalendarMonth');
    const body=document.getElementById('luvrCalendarBody'),info=document.getElementById('luvrCalendarInfo');
    const error=document.getElementById('luvrCalendarError'),editor=document.getElementById('luvrCalendarEditor');
    const refresh=document.getElementById('luvrCalendarRefresh');let editing=null;
    const controller=new LuvrCalendarController(luvrHistoryRequest,render,message=>{error.textContent=message;error.hidden=false;});
    document.addEventListener('luvr-rail-deleted',event=>{
        if(controller.selection?.employee!==event.detail.employee_id)return;
        editing=null;editor.hidden=true;controller.epoch++;controller.busy=false;controller.data=null;
        controller.render(controller);controller.load();
    });
    const now=new Date();month.value=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
    async function select(){editing=null;editor.hidden=true;error.hidden=true;await controller.select(employee.value,month.value);}
    employee.onchange=select;month.onchange=select;
    refresh.onclick=()=>{error.hidden=true;controller.load();};
    document.getElementById('luvrCalendarNavButton').onclick=async()=>{
        showMainSection(page,document.getElementById('luvrCalendarNavButton'));error.hidden=true;
        try{
            const previous=employee.value;
            const groups=await Promise.all([luvrHistoryRequest('/api/employees'),luvrHistoryRequest('/api/employees?archived=true')]);
            employee.replaceChildren(new Option('Выберите сотрудника',''));
            const unique=new Map(groups.flatMap(g=>g.items).map(item=>[item.id,item]));
            for(const item of [...unique.values()].sort((a,b)=>a.full_name.localeCompare(b.full_name,'ru'))){
                employee.append(new Option(item.full_name+(item.is_archived?' — архив':''),item.id));
            }
            employee.value=previous;await select();
        }catch(e){error.textContent=e.message;error.hidden=false;}
    };
    const value=document.getElementById('luvrCalendarValue'),comment=document.getElementById('luvrCalendarComment');
    for(const [code,label] of Object.entries(LUVR_CALENDAR_VALUES))value.append(new Option(label,code));
    document.getElementById('luvrCalendarCancel').onclick=()=>{editing=null;editor.hidden=true;};
    editor.onsubmit=async event=>{
        event.preventDefault();if(!editing)return;
        const target=editing;error.hidden=true;
        if(await controller.change(target,value.value,comment.value)){if(editing===target){editing=null;editor.hidden=true;}}
    };
    function render(state){
        refresh.disabled=state.busy||!state.selection;
        document.getElementById('luvrCalendarSave').disabled=state.busy;
        body.replaceChildren();
        if(!state.data){info.textContent=state.busy?'Расчёт…':'Выберите сотрудника и месяц';return;}
        const data=state.data;
        const mode=data.mode==='SHIFT'?'Вахтовый график':data.mode==='FIVE_TWO'?'График 5/2':data.mode==='CONFIGURATION_ERROR'?'Ошибка конфигурации должности':'График должности не указан — автоматический расчёт перемещений не выполняется';
        info.textContent=`${data.full_name}${data.is_archived?' (архив)':''} · ${mode}${state.busy?' · Обновление…':''}`;
        for(const day of data.days){
            const row=document.createElement('tr');row.dataset.date=day.date;
            if(day.manually_changed)row.classList.add('luvr-day-manual');
            const cell=text=>{const td=document.createElement('td');td.textContent=text;row.append(td);return td;};
            cell(day.date.split('-').reverse().join('.'));cell(day.auto_display);cell(day.final_display);
            cell(day.manually_changed?'Да':'Нет');
            const detail=cell('');
            const label=document.createElement('div');label.textContent=day.calculation_status==='NEEDS_REVIEW'?'Требует проверки':LUVR_SOURCES[day.final_source_type]||'';detail.append(label);
            if(day.is_sick){const note=document.createElement('small');note.textContent='Есть период болезни';detail.append(note);}
            if(day.movement_ids.length){const note=document.createElement('small');note.textContent='События № '+day.movement_ids.join(', ');detail.append(note);}
            if(day.override_code){const note=document.createElement('small');note.textContent='Ручное значение: '+LUVR_CALENDAR_VALUES[day.override_code]+(day.override_comment?' · '+day.override_comment:'');detail.append(note);}
            for(const warning of day.warnings){const note=document.createElement('div');note.className='luvr-day-warning';note.textContent=warning.message;detail.append(note);}
            const actions=cell('');
            const edit=document.createElement('button');edit.type='button';edit.className='secondary-button';edit.textContent='Редактировать';edit.dataset.action='edit-day';edit.disabled=state.busy;
            edit.onclick=()=>{editing=day;document.getElementById('luvrCalendarEditDate').textContent=day.date.split('-').reverse().join('.');value.value=day.override_code||day.final_code;comment.value=day.override_comment||'';editor.hidden=false;editor.scrollIntoView({block:'nearest'});value.focus();};actions.append(edit);
            if(day.override_id){const undo=document.createElement('button');undo.type='button';undo.className='secondary-button';undo.textContent='Вернуть автоматическое значение';undo.dataset.action='restore-day';undo.disabled=state.busy;
                undo.onclick=async()=>{error.hidden=true;editing=null;editor.hidden=true;await controller.change(day,null,'',true);};actions.append(undo);}
            body.append(row);
        }
    }
    render(controller);return controller;
}
if(typeof document!=='undefined')initLuvrCalendar();
if(typeof module!=='undefined')module.exports={LuvrCalendarController,LUVR_CALENDAR_VALUES};
