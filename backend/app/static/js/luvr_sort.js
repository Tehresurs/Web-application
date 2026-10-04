const LUVR_SORT_FIELDS=['full_name','position_name','specialty','work_location','work_schedule','current_state','work_days_total','travel_days_total','off_shift_days_total','downtime_days_total'];
const luvrCollator=new Intl.Collator('ru',{sensitivity:'base',numeric:true});
function luvrSortValue(employee,field){
    if(field.endsWith('_total'))return employee.totals?.[field]??null;
    if(field==='current_state'){
        const d=employee.duration||{};
        if(d.current_state==='DISMISSED')return 'Уволен';
        if(d.current_state==='NOT_APPLICABLE')return null;
        if(d.is_sick)return 'Болеет';
        return {ON_SHIFT:'Вахта',OFF_SHIFT:'МВ',UNKNOWN:'Не определено'}[d.current_state]||null;
    }
    if(field==='work_location')return {OBJECT:'Объект',OFFICE:'Офис'}[employee[field]]||null;
    if(field==='work_schedule')return {SHIFT:'Вахта',FIVE_TWO:'5/2'}[employee[field]]||null;
    return employee[field]?.trim().replace(/\s+/g,' ')||null;
}
function sortLuvrEmployees(employees,field='full_name',direction='asc'){
    if(!LUVR_SORT_FIELDS.includes(field))field='full_name';
    return [...employees].sort((a,b)=>{
        const x=luvrSortValue(a,field),y=luvrSortValue(b,field);
        if(x===null&&y!==null)return 1;if(y===null&&x!==null)return -1;
        const order=x===null?0:typeof x==='number'?x-y:luvrCollator.compare(x,y);
        return order*(direction==='desc'?-1:1)||luvrCollator.compare(luvrSortValue(a,'full_name')||'',luvrSortValue(b,'full_name')||'')||a.employee_id-b.employee_id;
    });
}
if(typeof module!=='undefined')module.exports={sortLuvrEmployees,luvrSortValue,LUVR_SORT_FIELDS};
