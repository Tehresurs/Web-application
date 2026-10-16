const assert=require('node:assert/strict');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
 const clickText=text=>ev(`Array.from(document.querySelectorAll('#employeeProfile button')).find(b=>b.textContent===${JSON.stringify(text)}).click()`);
 const ready=()=>wait(`!document.querySelector('#employeeProfilePanel').textContent.includes('Загрузка')&&document.getElementById('employeeStateBadge').textContent!=='Загрузка…'`);
 const fill=values=>ev(`(()=>{const f=document.querySelector('[data-absence-form]');for(const [key,value] of Object.entries(${JSON.stringify(values)}))f.elements[key].value=value;f.requestSubmit();})()`);
 try{
  await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});await call('Page.navigate',{url:'http://127.0.0.1:8881/'});
  await wait('typeof renderEmployeeAbsences==="function" && typeof loadEmployees==="function"');
  await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');
  await ev(`document.querySelector('#employeeList tr[data-employee="3"]').click()`);await ready();
  const today=await ev('employeeToday()');const yesterday=new Date(today+'T00:00:00Z');yesterday.setUTCDate(yesterday.getUTCDate()-1);const end=yesterday.toISOString().slice(0,10);
  const normal=await ev('document.getElementById("employeeStateBadge").textContent');assert.ok(['Рабочий день','Выходной'].includes(normal));
  assert.equal(await ev('document.querySelectorAll(".employee-header-badges .ui-badge").length'),2);
  assert.ok(await ev(`(()=>{const c=document.querySelectorAll('.employee-data-columns > section');return Math.abs(c[0].getBoundingClientRect().top-c[1].getBoundingClientRect().top)<1;})()`));
  await clickText('История');await ready();await clickText('+ Другое');
  await fill({reason:'Отпуск',date_from:today,date_to:today,comment:'Проверка'});await wait('document.getElementById("employeeStateBadge").textContent==="Отпуск"');await ready();
  await clickText('Изменить');await fill({reason:'Обучение',date_from:today,date_to:today});await wait('document.getElementById("employeeStateBadge").textContent==="Обучение"');await ready();
  await clickText('Изменить');await fill({date_from:end,date_to:end});await wait(`document.getElementById('employeeStateBadge').textContent===${JSON.stringify(normal)}`);await ready();
  await clickText('Изменить');await fill({date_from:today,date_to:today});await wait('document.getElementById("employeeStateBadge").textContent==="Обучение"');await ready();
  await clickText('Уволен');await fill({date_from:today});await wait('document.getElementById("employeeStateBadge").textContent==="Уволен"');await ready();
  const employee=await ev(`(async()=>{const d=await(await fetch('/api/employees?include_archived=true')).json();return d.items.find(e=>e.id===3);})()`);assert.equal(employee.dismissal_date,today);
  await ev('window.confirm=()=>true');await clickText('Удалить');await wait('document.querySelectorAll("[data-absence-id]").length===0');assert.equal(await ev('document.getElementById("employeeStateBadge").textContent'),'Уволен');
  await clickText('Основные данные');await ready();assert.ok(await ev(`document.querySelector('#employeeProfile').textContent.includes(luvrLocalDate(${JSON.stringify(today)}))`));
  await ev(`document.querySelector('#employeeList tr[data-employee="1"]').click()`);await ready();assert.equal(await ev('document.getElementById("employeeStateBadge").textContent'),'Не определено');
  await ev(`employeeAbsenceRequest('/api/employees/1/luvr/movements','POST',{movement_type:'ARRIVAL',transport_type:'SELF',event_datetime:employeeToday()+'T07:00:00'})`);
  await ev('renderEmployeeProfile()');await ready();assert.equal(await ev('document.getElementById("employeeStateBadge").textContent'),'Вахта');
  await clickText('История');await ready();await clickText('Прибыл / Убыл');await wait('!document.getElementById("employeeModal").hidden');assert.ok(await ev('document.getElementById("employeeLuvrHistory").open'));await ev('document.getElementById("employeeModalCancel").click()');await ready();
  await clickText('Управлять исключениями');await wait('!document.getElementById("employeeModal").hidden');await ev('document.getElementById("employeeModalCancel").click()');
  assert.deepEqual(errors,[]);console.log('PASS: two badges, desktop columns, absence CRUD, inclusive dates/end restores state, dismissal priority/existing date, movement/exception forms, no JS errors');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
