/* Review-only state: the server validates source bytes and owns persistent rules. */
function reviewApproved(report, field) {
    return report.review_options?.fields?.[field]?.approved === true;
}
function reviewBaseProblems(report) {
    return (report.problems || []).filter(text => {
        const value = String(text).toLowerCase();
        return !(reviewApproved(report, 'general_contractor') && /генподряд|^по[: ]/.test(value)) &&
            !(reviewApproved(report, 'subcontractor') && value.includes('субподряд'));
    });
}
function reportReviewIssues(report) {
    if (report.control_saved) return [];
    const issues = [...reviewBaseProblems(report), ...(report.server_problems || []), ...(report.review_error ? [report.review_error] : [])];
    for (const [field, label] of [['employee','Инженер'],['object','Объект'],['general_contractor','ПО'],['subcontractor','Субподрядчик']]) {
        if (reviewApproved(report,field)) continue;
        if (field === 'subcontractor' && !report.review_options?.enabled && !report.subcontractor) continue;
        if (report[`${field}_status`] !== 'found') issues.push(`${label}: ${report.review_options?.fields?.[field]?.absent ? 'согласуйте отсутствие' : 'требуется сопоставление'}`);
    }
    if (!report.report_date) issues.push('Дата отчёта не определена');
    issues.push(...Object.values(report.alias_conflicts || {}));
    const key = reviewApproved(report,'general_contractor') ? 'null' : report.general_contractor_id;
    if ((!report.assignments_verified || !report.assignments?.[key]?.category_id) &&
        !issues.some(issue => String(issue).toLowerCase().startsWith('нет категории'))) issues.push('Нет категории');
    return [...new Set(issues)];
}
async function loadReportReviewOptions(report) {
    if (!report.source_path || !report.report_date) return;
    try {
        report.review_options = await apiPost('/api/daily-control-results/review-options',{path:report.source_path});
        report.server_problems=[];
        delete report.review_error;
    } catch(e) { report.review_error=e.message; }
}
function paintReportReviewSummary(report, container) {
    container.querySelector('[data-review-summary]')?.remove();
    const summary=document.createElement('div'); summary.dataset.reviewSummary='true';
    const issues=reportReviewIssues(report);
    summary.className=issues.length ? 'review-issues' : 'review-success';
    summary.textContent=issues.length ? issues.join('\n') : 'Замечания устранены';
    container.prepend(summary);
}
function reviewAbsenceControls(report,config,row) {
    const field=config.kind==='po' ? 'general_contractor' : config.kind==='subcontractor' ? 'subcontractor' : null;
    const state=report.review_options?.fields?.[field];
    if (!state?.absent) return false;
    const info=document.createElement('p');
    info.textContent=state.approved ? `Отсутствие согласовано${state.rule ? ' по правилу' : ' для этого отчёта'}. Значение остаётся пустым.` : 'Требуется согласовать отсутствие';
    row.append(info);
    for(const [label,rule] of [['Согласовать отсутствие',false],['Принять как правило',true]]) {
        const button=document.createElement('button'); button.type='button';button.className='secondary-button';button.textContent=label;
        button.disabled=rule ? state.rule : state.manual;
        button.onclick=async()=>{
            button.disabled=true;
            try {
                await apiPost('/api/daily-control-results/review-options',{path:report.source_path,field,as_rule:rule});
                for(const item of (rule ? window.processingReports : [report])) await loadReportReviewOptions(item);
                addProcessingLog('Информация',`${report.filename}: ${config.label} — ${label}`);
                renderReports(); if(window.processingReports[activeReportIndex]===report)openDetails(report);
            }catch(e){
                info.textContent=e.message;report.review_error=e.message;button.disabled=false;
                renderReports();
                if(window.processingReports[activeReportIndex]===report)paintReportReviewSummary(report,document.getElementById('databaseStatus'));
                reportSaver.sync();
            }
        };
        row.append(button);
    }
    return true;
}
async function renderReviewRules(container) {
    const details=document.createElement('details');details.className='review-rules';
    const title=document.createElement('summary');title.textContent='Правила согласования отсутствия';details.append(title);container.append(details);
    try {
        const response=await fetch('/api/daily-control-results/absence-rules');const data=await response.json();
        if(!response.ok)throw Error(data.detail||'Не удалось загрузить правила');
        for(const field of ['general_contractor','subcontractor']) {
            const rule=data.items.find(i=>i.field===field); const line=document.createElement('p');
            line.textContent=`${field==='general_contractor'?'ПО':'Субподрядчик'}: ${rule?.enabled?'правило включено':'правило выключено'} `;
            if(rule?.enabled){const button=document.createElement('button');button.type='button';button.className='secondary-button';button.textContent='Отменить правило';
                button.onclick=async()=>{button.disabled=true;try{
                    const res=await fetch('/api/daily-control-results/absence-rules/'+field,{method:'DELETE'});
                    if(!res.ok)throw Error('Правило не отменено');
                    for(const report of window.processingReports)await loadReportReviewOptions(report);
                    renderReports();const report=window.processingReports[activeReportIndex];if(report)openDetails(report);
                }catch(e){
                    line.append(document.createTextNode(e.message));button.disabled=false;
                    const report=window.processingReports[activeReportIndex];
                    if(report){
                        report.review_error=e.message;renderReports();paintReportReviewSummary(report,container);reportSaver.sync();
                    }
                }};line.append(button);}
            details.append(line);
        }
    }catch(e){
        details.append(document.createTextNode(e.message));
        const report=window.processingReports[activeReportIndex];
        if(report){
            report.review_error=e.message;renderReports();paintReportReviewSummary(report,container);reportSaver.sync();
        }
    }
}
async function renderReviewCategory(report,container) {
    report.assignments_verified=false;
    const section=document.createElement('section');section.className='review-category';container.append(section);
    const title=document.createElement('h4');title.textContent='Категория и назначение';section.append(title);
    const message=document.createElement('p');section.append(message);
    if(getFinalReportStatus(report)!=='verified' || !report.entity_id || !report.employee_id){message.textContent='Нет категории. Сначала согласуйте сотрудника, объект и организации.';return;}
    const po=reviewApproved(report,'general_contractor')?null:report.general_contractor_id;
    try {
        const [ar,cr]=await Promise.all([fetch(`/api/daily-control-results/review-assignments/${report.employee_id}`),fetch('/api/object-categories')]);
        const [assignments,categories]=await Promise.all([ar.json(),cr.json()]);
        if(!ar.ok||!cr.ok)throw Error(assignments.detail||categories.detail||'Не удалось прочитать закрепления и категории');
        if(!section.isConnected)return;
        const matching=assignments.items.filter(i=>Number(i.entity_id)===Number(report.entity_id) && (i.po_id??null)===(po??null));
        report.assignments||={};delete report.assignments[String(po)];
        if(matching.length>1)throw Error('Найдено несколько закреплений. Сохранение категории заблокировано до устранения неоднозначности.');
        const selectionKey=JSON.stringify([report.employee_id,report.entity_id,po]);
        report.categoryDrafts||={};
        const draft=report.categoryDrafts[selectionKey];
        let existing=matching[0];
        if(!report.control_saved && !draft){
            const selected=await apiPost('/api/daily-control-results/review-category',{path:report.source_path,employee_id:report.employee_id,entity_id:report.entity_id,po_id:po,automatic:true});
            if(!section.isConnected)return;
            existing=selected.item||existing;
        }
        if(existing?.category_id && !draft)report.assignments[String(po)]=existing;
        report.assignments_verified=true;
        const select=document.createElement('select');select.setAttribute('aria-label','Категория отчёта');select.add(new Option('Выберите категорию',''));
        for(const item of flattenAssignmentCategories(categories.items))select.add(new Option(item.label,item.id));
        select.value=draft?draft.value:existing?.category_id?String(existing.category_id):'';
        message.textContent=existing?.category_id?`Категория: ${existing.category_name}`:'Нет категории';
        const save=document.createElement('button');save.type='button';save.className='secondary-button';save.textContent='Сохранить категорию';
        select.onchange=()=>{report.categoryDrafts[selectionKey]={value:select.value};delete report.assignments[String(po)];message.textContent='Изменение категории ещё не сохранено';renderReports();paintReportReviewSummary(report,container);reportSaver.sync();};
        save.onclick=async()=>{
            if(!select.value){message.textContent='Нет категории: выберите значение';return;}
            save.disabled=true;
            try {
                const result=await apiPost('/api/daily-control-results/review-category',{path:report.source_path,employee_id:report.employee_id,entity_id:report.entity_id,po_id:po,category_id:Number(select.value)});
                delete report.categoryDrafts[selectionKey];
                report.assignments[String(po)]=result.item;report.assignments_verified=true;
                delete report.review_error;report.server_problems=[];
                message.textContent=`Категория сохранена: ${result.item.category_name}`;
                renderReports();paintReportReviewSummary(report,container);reportSaver.sync();
            }catch(e){message.textContent=e.message;report.review_error=e.message;renderReports();paintReportReviewSummary(report,container);}
            finally{save.disabled=false;}
        };
        section.append(select,save);
    }catch(e){message.textContent=e.message;report.review_error=e.message;}
    finally{renderReports();paintReportReviewSummary(report,container);reportSaver.sync();}
}
if(typeof module!=='undefined')module.exports={reviewApproved,reviewBaseProblems,reportReviewIssues};
