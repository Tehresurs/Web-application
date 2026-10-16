'use strict';
function deploymentTableRows(report){
    return report.rows.map(row=>['number','object_name','organization_name','employee_name','equipment','phone','transport'].map(key=>row[key]??''));
}
function initDeployment(){
    const el=id=>document.getElementById(id), date=el('deploymentDate'), status=el('deploymentStatus'), download=el('deploymentExport');
    let generation=0, loadedDate=null;
    date.value=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Yekaterinburg',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    function invalidate(){generation++;loadedDate=null;download.disabled=true;el('deploymentReport').hidden=true;el('deploymentWarnings').replaceChildren();status.textContent='Выберите дату и сформируйте отчёт.';}
    function render(data){
        el('deploymentWarnings').replaceChildren();
        if(data.warnings.length){
            const details=document.createElement('details'), summary=document.createElement('summary'), list=document.createElement('ul');
            summary.textContent=`Предупреждения: ${data.warnings.length}`;details.append(summary,list);
            for(const warning of data.warnings){const li=document.createElement('li');li.textContent=[warning.employee_name,warning.message,(warning.facts||[]).map(f=>f.object_name||'').join(', '),(warning.details||[]).join(', ')].filter(Boolean).join(' — ');list.append(li);}
            el('deploymentWarnings').append(details);
        }
        el('deploymentReport').hidden=!data.formed;
        if(!data.formed){status.textContent='ЛУВР на выбранный месяц не сформирован. Численность не определена.';return;}
        el('deploymentReportDate').textContent=data.date_label;
        const head=document.createElement('tr');
        for(const label of data.headers){const th=document.createElement('th');th.textContent=label;head.append(th);}
        el('deploymentHead').replaceChildren(head);
        el('deploymentRows').replaceChildren();
        deploymentTableRows(data).forEach((values,i)=>{const tr=document.createElement('tr');tr.dataset.source=data.rows[i].source||'UNKNOWN';tr.title=data.rows[i].source==='FACT'?'Подтверждённый факт':data.rows[i].source==='PLAN'?'План':'Назначение неизвестно';for(const value of values){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}el('deploymentRows').append(tr);});
        el('deploymentTotals').replaceChildren();
        for(const [key,label] of [['objects','Всего объектов'],['organizations','Всего ПО'],['specialists','Всего специалистов СК на объектах']]){const p=document.createElement('span');p.textContent=`${label}: ${data.totals[key]}`;el('deploymentTotals').append(p);}
        loadedDate=data.date;download.disabled=false;status.textContent=data.rows.length?'Отчёт сформирован.':'На выбранную дату работающих сотрудников нет.';
    }
    async function load(){
        if(!date.reportValidity())return;
        invalidate();const current=++generation, target=date.value;status.textContent='Формирование отчёта…';
        try{const response=await fetch(`/api/deployment/report?date=${encodeURIComponent(target)}`);const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось сформировать отчёт');if(current===generation)render(data.item);}
        catch(error){if(current===generation)status.textContent=error.message;}
    }
    el('deploymentNavButton').addEventListener('click',()=>{showMainSection(el('deploymentPage'),el('deploymentNavButton'));load();});
    el('deploymentRefresh').addEventListener('click',load);date.addEventListener('change',invalidate);
    download.addEventListener('click',async()=>{
        if(!loadedDate||loadedDate!==date.value)return;
        const target=loadedDate;download.disabled=true;
        try{const response=await fetch(`/api/deployment/report/export?date=${encodeURIComponent(target)}${el('deploymentIncludeAnalysis').checked?'&include_analysis=true':''}`);if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выгрузить Excel');}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`Расстановка_${target}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
        catch(error){status.textContent=error.message;}
        finally{download.disabled=loadedDate!==date.value||!loadedDate;}
    });
}
if(typeof document!=='undefined')initDeployment();
if(typeof module!=='undefined')module.exports={deploymentTableRows};
