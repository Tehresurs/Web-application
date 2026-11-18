(() => {
    'use strict';
    const get = id => document.getElementById(id);
    const nav = get('vouNavButton');
    if (!nav) return;
    const status = get('vouArchiveStatus');
    const rows = get('vouArchiveRows');
    const refresh = get('vouArchiveRefresh');
    const tabs = [get('vouCreateTab'),get('vouPersonnelTab'),get('vouArchiveTab')];
    function activateTab(index,focus=false) {
        tabs.forEach((tab,i) => {
            tab.setAttribute('aria-selected',String(i===index));
            tab.tabIndex=i===index?0:-1;
            get(tab.getAttribute('aria-controls')).hidden=i!==index;
        });
        if (focus) tabs[index].focus();
        if (index===2) load();
        if (index===1) window.VouPersonnel.load();
    }
    tabs.forEach((tab,index) => {
        tab.addEventListener('click',()=>activateTab(index));
        tab.addEventListener('keydown',event=>{
            let next;
            if (event.key==='ArrowRight') next=(index+1)%tabs.length;
            else if (event.key==='ArrowLeft') next=(index+tabs.length-1)%tabs.length;
            else if (event.key==='Home') next=0;
            else if (event.key==='End') next=tabs.length-1;
            else return;
            event.preventDefault();activateTab(next,true);
        });
    });

    const form = get('vouGenerateForm');
    const generateButton = get('vouGenerate');
    const generationStatus = get('vouGenerateStatus');
    const warnings = get('vouWarnings');
    const today = new Date();
    get('vouMonth').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;
    function formatWarning(item) {
        if (item.code==='MISSING_AOS_DESCRIPTION') return `Не заполнено описание работ: ${item.position_name}`;
        const date = /^\d{4}-\d{2}-\d{2}$/.test(item.date || '') ?
            `${item.date.slice(8,10)}.${item.date.slice(5,7)}.${item.date.slice(0,4)}` : item.date;
        const identity = [item.full_name,date].filter(Boolean).join(', ');
        return `${identity ? `${identity}: ` : ''}${item.message || item.code}`;
    }
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (generateButton.disabled || !form.reportValidity()) return;
        const [year,month] = get('vouMonth').value.split('-').map(Number);
        generateButton.disabled = true;
        warnings.replaceChildren();
        delete warnings.dataset.state;
        generationStatus.dataset.state='loading';
        generationStatus.textContent = 'Формирование и проверка в Microsoft Excel… Дождитесь завершения.';
        try {
            const response = await fetch('/api/vou/reports', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({year,month})});
            const body = await response.json();
            if (!response.ok) {
                const detail = body.detail;
                if (Array.isArray(detail?.errors) && detail.errors.length) {
                    generationStatus.dataset.state='error';
                    generationStatus.textContent = `${detail.message || 'Данные ВОУ требуют проверки'} Найдено ошибок: ${detail.errors.length}.`;
                    warnings.dataset.state='error';
                    for (const item of detail.errors) {
                        const li = document.createElement('li');
                        li.textContent = item.message || item.code || 'Ошибка проверки данных ВОУ';
                        warnings.append(li);
                    }
                    return;
                }
                throw new Error(typeof detail==='string' ? detail : (detail?.message || 'Не удалось сформировать Отчет ВОУ'));
            }
            generationStatus.dataset.state='success';
            generationStatus.textContent = 'Отчёт проверен и сохранён в архиве. ';
            const link = document.createElement('a');
            link.textContent = 'Скачать XLSM';
            link.href = `/api/vou/reports/${encodeURIComponent(body.item.id)}/file`;
            generationStatus.append(link);
            for (const item of body.warnings || []) {
                const li = document.createElement('li');
                li.textContent = formatWarning(item);
                warnings.append(li);
            }
            await load();
            window.VouPersonnel.select(body.item.id);
            activateTab(1);
        } catch (error) {generationStatus.dataset.state='error';generationStatus.textContent=error.message;}
        finally {generateButton.disabled=false;}
    });

    async function load() {
        refresh.disabled = true;
        status.dataset.state='loading';
        get('vouArchiveEmpty').hidden=true;
        get('vouArchiveTable').hidden=true;
        status.textContent = 'Загрузка архива…';
        rows.replaceChildren();
        try {
            const response = await fetch('/api/vou/reports');
            if (!response.ok) throw new Error('Не удалось загрузить архив ВОУ');
            const body = await response.json();
            get('vouArchiveCount').textContent=body.items.length;
            get('vouArchiveEmpty').hidden=body.items.length!==0;
            get('vouArchiveTable').hidden=body.items.length===0;
            for (const item of body.items) {
                const tr = document.createElement('tr');
                const settings = item.settings;
                const contractDate = settings.contract_date.split('-').reverse().join('.');
                const contract = `${settings.contract_number} от ${contractDate}, rev. ${settings.contract_revision}`;
                for (const value of [`${String(item.month).padStart(2,'0')}.${item.year}`,
                    new Date(item.generated_at).toLocaleString('ru-RU'), contract,
                    (item.total_cents/100).toLocaleString('ru-RU',{minimumFractionDigits:2})]) {
                    const td = document.createElement('td'); td.textContent = value; tr.append(td);
                }
                const td = document.createElement('td');
                const link = document.createElement('a');
                link.className='vou-download';
                link.textContent = 'Скачать XLSM';
                link.href = `/api/vou/reports/${encodeURIComponent(item.id)}/file`;
                const preview=document.createElement('button');
                preview.type='button';preview.className='vou-download';preview.textContent='Персонал';
                preview.addEventListener('click',()=>{window.VouPersonnel.select(item.id);activateTab(1);});
                td.append(preview,document.createTextNode(' '),link); tr.append(td); rows.append(tr);
            }
            status.dataset.state='ready';
            status.textContent = body.items.length ? `Отчётов: ${body.items.length}.` : 'Сформированных отчётов пока нет.';
            if (body.warnings.length) status.textContent += ` Недоступных отчётов: ${body.warnings.length}.`;
        } catch (error) { status.dataset.state='error';status.textContent = error.message; }
        finally { refresh.disabled = false; }
    }
    nav.addEventListener('click', () => {showMainSection(get('vouPage'),nav);load();});
    refresh.addEventListener('click',load);
    get('vouOpenSettings').addEventListener('click',()=>get('settingsNavButton').click());
})();
