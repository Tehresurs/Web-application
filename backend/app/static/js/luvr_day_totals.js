const LUVR_DAY_TOTAL_ROWS=[['work_equivalent','\u0418\u0442\u043e\u0433\u043e']];
function renderLuvrDayTotals(footer,data){
    footer.replaceChildren();if(!data?.formed)return;
    for(const [key,label] of LUVR_DAY_TOTAL_ROWS){
        const tr=document.createElement('tr');tr.dataset.dayTotal=key;
        const cell=text=>{const td=document.createElement('td');td.textContent=text;tr.append(td);return td;};
        cell('');const title=document.createElement('th');title.scope='row';title.textContent=label;title.className='luvr-name';tr.append(title);
        for(let i=0;i<6;i++)cell('');
        for(const day of data.day_totals){const td=cell(String(day[key]).replace('.',','));td.dataset.totalDate=day.date;}
        for(const field of ['work_days_total','travel_days_total',null,'downtime_days_total']){
            const td=cell(field?String(data.employees.reduce((sum,e)=>sum+e.totals[field],0)).replace('.',','):'');
            if(field)td.dataset.total=field;
        }
        cell('');
        footer.append(tr);
    }
}
if(typeof module!=='undefined')module.exports={LUVR_DAY_TOTAL_ROWS,renderLuvrDayTotals};
