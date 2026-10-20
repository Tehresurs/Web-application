(() => {
    'use strict';
    const get=id=>document.getElementById(id);
    let selected=null,loaded=null,sequence=0;
    const number=(value,total=false)=>typeof value==='number' ? value.toLocaleString('ru-RU',{minimumFractionDigits:total?2:0,maximumFractionDigits:2}) : (value??'');
    async function json(url) {
        const response=await fetch(url);
        const body=await response.json();
        if (!response.ok) throw new Error(typeof body.detail==='string'?body.detail:'Не удалось открыть результат отчёта');
        return body;
    }
    function render(report) {
        const blocks=report.verification?.com?.fresh_excel?.readback_blocks;
        const address=Object.keys(blocks||{}).find(key=>/^B14:AL\d+$/.test(key));
        const grid=address&&blocks[address];
        if (!Array.isArray(grid)||grid.some(row=>!Array.isArray(row)||row.length!==37)) throw new Error('В этом отчёте отсутствует сохранённая таблица «Персонал»');
        const length=new Date(Date.UTC(report.year,report.month,0)).getUTCDate();
        const columns=[0,1,2,3,...Array.from({length},(_,i)=>4+i),35,36];
        const titles=['№','Объект / подобъект','Описание работ','Ф.И.О. сотрудника',...Array.from({length},(_,i)=>String(i+1).padStart(2,'0')),'Итого, чел.-дни','Количество смен'];
        const head=document.createElement('tr');
        titles.forEach((title,index)=>{const th=document.createElement('th');th.scope='col';th.textContent=title;if(index<4)th.className='vou-pin vou-col-'+index;head.append(th);});
        get('vouPersonnelHead').replaceChildren(head);
        const fragment=document.createDocumentFragment();
        grid.forEach((values,index)=>{
            if(values.every(v=>v==null||v===''))return;
            const row=document.createElement('tr');row.dataset.excelRow=String(index+14);
            const grand=values[0]==='ИТОГО';
            const category=!grand&&!values[3]&&values[1]&&/^[1-6](?:\.\d+)?\.?$/.test(String(values[0]));
            if(grand) row.className='vou-personnel-grand';
            else if(category)row.className=String(values[0]).replace(/\.$/,'').includes('.')?'vou-personnel-subcategory':'vou-personnel-category';
            columns.forEach((source,index)=>{
                const td=document.createElement('td');td.textContent=number(values[source],source===35);
                if(index<4)td.className='vou-pin vou-col-'+index;
                if(source>=4&&source<=34)td.classList.add('vou-personnel-day');
                if(source===35)td.classList.add('vou-personnel-row-total');
                row.append(td);
            });
            fragment.append(row);
        });
        get('vouPersonnelRows').replaceChildren(fragment);
        get('vouPersonnelPeriod').textContent=`Отчёт за ${String(report.month).padStart(2,'0')}.${report.year}`;
        get('vouPersonnelTotal').textContent=number(report.total_cents/100,true);
        get('vouPersonnelDownload').href=`/api/vou/reports/${encodeURIComponent(report.id)}/file`;
        for(const id of ['vouPersonnelSummary','vouPersonnelScroll','vouPersonnelDownload'])get(id).hidden=false;
    }
    window.VouPersonnel={
        select(id){selected=id;},
        async load(){
            if(selected&&selected===loaded&&!get('vouPersonnelScroll').hidden)return;
            const token=++sequence;
            const status=get('vouPersonnelStatus');status.dataset.state='loading';status.textContent='Загрузка листа «Персонал»…';
            for(const id of ['vouPersonnelSummary','vouPersonnelScroll','vouPersonnelDownload'])get(id).hidden=true;
            try{
                let id=selected;
                if(!id){const archive=await json('/api/vou/reports');id=archive.items[0]?.id;}
                if(token!==sequence)return;
                if(!id){status.dataset.state='ready';status.textContent='Сначала сформируйте отчёт или выберите его в архиве.';return;}
                const body=await json(`/api/vou/reports/${encodeURIComponent(id)}`);
                if(token!==sequence)return;
                render(body.item);selected=id;loaded=id;
                status.dataset.state='ready';status.textContent='';
            }catch(error){if(token===sequence){status.dataset.state='error';status.textContent=error.message;}}
        }
    };
})();
