(() => {
 'use strict';
 const originalFetch=window.fetch.bind(window);
 window.fetch=(input,options={})=>{
   const method=(options.method||input?.method||'GET').toUpperCase();
   if(!['GET','HEAD'].includes(method))return Promise.resolve(new Response(JSON.stringify({detail:'Доступ только для просмотра',message:'Доступ только для просмотра'}),{status:403,headers:{'Content-Type':'application/json'}}));
   return originalFetch(input,options);
 };
 const write=/^(добавить|изменить|редактировать|удалить|сохранить|подтвердить|согласовать|загрузить|обработать|перепроверить|выбрать файл|выбрать папку|назначить|отменить дк|аннулировать|восстановить|архивировать|сформировать|исправить|применить|заменить|принять|отклонить|исключить|снять)/i;
 const ids=['vouGenerate','luvrMonthForm','luvrMonthAdd','luvrMonthExport','deploymentExport','chooseFolderButton','selectFolderButton','processFolderButton','addEmployeeButton'];
 let pending=false;
 function mark(){
   pending=false;
   document.documentElement.classList.add('demo-viewer');
   document.querySelectorAll('button,input[type=submit]').forEach(button=>{
     if(button.id==='deploymentRefresh')return; // GET projection, not file processing.
     if(ids.includes(button.id)||write.test((button.textContent||button.value||'').trim().replace(/^[^A-Za-zА-Яа-яЁё]+/,''))||button.matches('.edit-position,.delete-position,.edit-employee,.delete-employee,.edit-po,.delete-po')){
       button.classList.add('demo-write');button.disabled=true;button.title='Только просмотр';
     }
   });
   document.querySelectorAll('.pm-inner tr[data-row-key] td:nth-child(-n+5) button,.pm-editor select,#vouSettingsForm input,#luvrHeaderForm input,#luvrHeaderForm textarea,input[type=file]').forEach(control=>{
     control.classList.add('demo-disabled');control.disabled=true;
   });
 }
 function schedule(){if(!pending){pending=true;requestAnimationFrame(mark);}}
 new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
 document.addEventListener('click',event=>{
   if(event.target.closest?.('.demo-write,.demo-disabled')){event.preventDefault();event.stopImmediatePropagation();}
 },true);
 document.addEventListener('submit',event=>{
   if(event.target.id!=='journalFilters'){event.preventDefault();event.stopImmediatePropagation();}
 },true);
 document.addEventListener('DOMContentLoaded',()=>{
   mark();
   const banner=document.createElement('div');banner.className='demo-viewer-banner';banner.setAttribute('role','status');banner.textContent='Демонстрационный доступ · Только просмотр';
   document.querySelector('.main')?.prepend(banner);
   originalFetch('/api/demo/me').then(r=>r.json()).then(me=>{
     const header=document.querySelector('.header-user');if(header)header.textContent=me.username+' · Только просмотр';
   }).catch(()=>{});
 });
})();
