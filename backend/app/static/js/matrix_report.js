/* One-file review launched from a selected matrix day. */
function matrixReportNode(tag,text){const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;}
function matrixReportButton(text,fn){const b=matrixReportNode('button',text);b.type='button';b.className='secondary-button';b.onclick=fn;return b;}
function matrixReportReturn(context){
    closeDetails();showMainSection(document.getElementById('productionMatrixPage'),document.getElementById('productionMatrixNavButton'));
    document.dispatchEvent(new CustomEvent('matrix-report-open',{detail:context}));
}
async function matrixReportSource(cell,container){
    let box=container.querySelector('[data-matrix-source]');if(box){box.remove();return;}
    box=matrixReportNode('div','Проверка источника…');box.dataset.matrixSource='true';container.append(box);
    try{
        const response=await fetch('/api/daily-control-results/facts/'+cell.source_fact_id);const result=await response.json();
        if(!response.ok)throw Error(result.detail||'Не удалось прочитать источник');
        box.replaceChildren();const f=result.item.fact;
        for(const text of ['Ежедневный факт сохранён: №'+f.id,'Дата: '+f.report_date,'Сотрудник: '+(f.employee_name||f.full_name),
            'Объект: '+(f.control_item_name||f.object_name||'—'),'ПО: '+(f.po_name||'—'),'Категория: '+(f.category_name||'—'),
            'Источник: '+f.source_file,'Проверка: '+PM_STATUS[cell.status],
            ...((cell.warnings||[]).map(w=>PM_WARNINGS[w]||w))])box.append(matrixReportNode('p',text));
        if(result.item.replacement_history.length){
            const history=matrixReportNode('details');history.append(matrixReportNode('summary','История замен за этот день: '+result.item.replacement_history.length));
            for(const entry of result.item.replacement_history){
                history.append(matrixReportNode('p','Замена №'+entry.id+' · '+entry.created_at));
                for(const old of entry.old_facts)history.append(matrixReportNode('p','Архив: факт №'+old.id+' · '+old.source_file+' · Категория: '+(old.category_name||old.category_id)));
            }
            box.append(history);
        }
    }catch(e){box.textContent=e.message;}
}
function matrixReportUpload(message){
    const input=document.createElement('input');input.type='file';input.accept='.docx';input.hidden=true;document.body.append(input);
    input.addEventListener('cancel',()=>input.remove(),{once:true});
    input.onchange=async()=>{
        const file=input.files[0];input.remove();if(!file)return;
        message.textContent='Загрузка и разбор одного отчёта…';
        const data=new FormData();data.append('file',file);
        try{
            const response=await fetch('/api/daily-control-results/upload-file',{method:'POST',body:data});const result=await response.json();
            if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Не удалось разобрать отчёт');
            const report=result.report;if(report.matrix_context)report.matrix_context.employee_name=report.full_name;
            report.matrix_candidates=result.candidates;
            window.processingReports.push(report);window.matrixActiveReport=report;
            showMainSection(document.getElementById('processingPage'),document.getElementById('processingNavButton'));
            searchInput.value='';statusFilter.value='all';dateFilter.value='all';
            renderReports();if(report.matrix_context)matrixReportPanel(report);else document.getElementById('matrixSingleReportPanel')?.setAttribute('hidden','');openDetails(report);message.textContent='Файл добавлен. Проверьте результат и сохраните его.';
        }catch(e){message.textContent=e.message;}
    };
    input.click();
}
function matrixReportPanel(report){
    let panel=document.getElementById('matrixSingleReportPanel');
    if(!panel){panel=matrixReportNode('section');panel.id='matrixSingleReportPanel';panel.className='card';document.getElementById('processingPage').prepend(panel);}
    panel.hidden=false;panel.replaceChildren();
    panel.append(matrixReportNode('h3','Отдельный отчёт за '+report.matrix_context.date),matrixReportNode('p','Выбранный сотрудник: '+(report.matrix_context.employee_name||report.matrix_context.employee_id)),
        matrixReportNode('p','Сохраняется только этот отчёт. «Замечания устранены» означает готовность; факт появится после нажатия «Сохранить результат».'));
    const status=matrixReportNode('p');status.dataset.matrixSaveStatus='true';panel.append(status);
    if(report.control_saved)status.textContent='Ежедневный факт сохранён: № '+(report.control_results||[]).map(r=>r.id).join(', ');
    panel.append(matrixReportButton('Открыть в матрице',()=>matrixReportReturn(report.matrix_context)),
        matrixReportButton('Вернуться к общему списку',()=>{window.matrixActiveReport=null;panel.hidden=true;renderReports();}));
    if(!report.control_saved && report.matrix_candidates?.length){
        const label=matrixReportNode('label','Действие после проверки: '),select=matrixReportNode('select');
        select.append(new Option('Добавить как новый отчёт',''));
        const seen=new Set();
        for(const f of report.matrix_candidates){
            if(seen.has(f.source_sha256))continue;seen.add(f.source_sha256);
            select.append(new Option('Заменить источник факта №'+f.id+': '+f.source_file,String(f.id)));
        }
        select.onchange=()=>{
            const old=report.matrix_candidates.find(f=>String(f.id)===select.value);
            report.matrix_context.replace_fact_id=old?.id||null;
            report.matrix_context.replace_source_sha256=old?.source_sha256||null;
            report.matrix_preview_signature=null;
            panel.querySelector('[data-replacement-preview]')?.remove();
            reportSaver.signature=null;reportSaver.sync();
        };
        label.append(select);panel.append(label);
    }
}
function matrixReportPreview(report,result,payload){
    report.control_results=result.results||report.control_results;
    if(result.saved){
        report.control_saved=true;
        const status=document.querySelector('#matrixSingleReportPanel [data-matrix-save-status]');
        if(status)status.textContent='Ежедневный факт сохранён: № '+(report.control_results||[]).map(r=>r.id).join(', ');
        document.dispatchEvent(new CustomEvent('daily-control-fact-saved',{detail:report.matrix_context}));
    }
    if(!result.replacement)return;
    const panel=document.getElementById('matrixSingleReportPanel');if(!panel)return;
    panel.querySelector('[data-replacement-preview]')?.remove();
    const box=matrixReportNode('div');box.dataset.replacementPreview='true';
    box.append(matrixReportNode('h4','Сравнение перед заменой'),matrixReportNode('p',result.replacement.note));
    const table=matrixReportNode('table');const header=matrixReportNode('tr');
    for(const text of ['Версия','Факт / назначение','Дата','Сотрудник','Объект (ID)','ПО (ID)','Категория (ID)'])header.append(matrixReportNode('th',text));
    table.append(header);
    for(const [label,rows] of [['Было',result.replacement.old_facts],['Станет',result.replacement.new_facts]]){
        for(const f of rows){const tr=matrixReportNode('tr');for(const text of [label,f.id||f.assignment_id,f.report_date||report.report_date,f.employee_id,f.control_item_name||f.entity_id||f.object_id,f.po_name||f.po_id||'Без ПО',f.category_name||f.category_id])tr.append(matrixReportNode('td',String(text??'—')));table.append(tr);}
    }
    box.append(table,matrixReportNode('p','Ручных корректировок будет архивировано: '+result.replacement.old_overrides.length));panel.append(box);
    report.matrix_preview_signature=JSON.stringify(payload);
    report.matrix_preview_token=result.replacement.token;
}
if(typeof document!=='undefined')document.addEventListener('matrix-report-review-result',event=>{
    const {payload,result}=event.detail;
    const report=window.processingReports.find(r=>r.source_path===payload.path && r.matrix_context);
    if(report)matrixReportPreview(report,result,payload);
});

async function matrixReportDelete(cell,card){
    const message=matrixReportNode('p','Проверка события…');card.append(message);
    try{
        const response=await fetch('/api/daily-control-results/facts/'+cell.source_fact_id);
        const source=await response.json();if(!response.ok)throw Error(source.detail||'Источник не найден');
        const f=source.item.fact;
        if(!window.confirm('Удалить событие за этот день?\n'+f.employee_name+' · '+f.report_date+'\nФакт №'+f.id+' · '+f.source_file+'\nОбъект: '+(f.control_item_name||f.object_name||'—')+'\nУдаляется только этот факт. Другие события и билеты сохраняются. Время остальных фактов может перераспределиться.'))
            {message.remove();return;}
        const deleted=await fetch('/api/daily-control-results/facts/'+f.id,{
            method:'DELETE',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({employee_id:f.employee_id,report_date:f.report_date,source_sha256:f.source_sha256.trim()})
        });
        const result=await deleted.json();if(!deleted.ok)throw Error(result.detail||'Не удалось удалить событие');
        message.textContent='Факт №'+f.id+' удалён. История сохранена.';
        document.dispatchEvent(new CustomEvent('daily-control-fact-saved',{detail:result}));
    }catch(e){message.textContent=e.message;}
}

if(typeof document!=='undefined')document.getElementById('addReportFileButton')?.addEventListener('click',()=>matrixReportUpload(document.getElementById('addReportFileStatus')));
