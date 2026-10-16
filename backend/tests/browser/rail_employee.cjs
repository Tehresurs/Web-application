// Mutating browser scenarios: isolated fixture server only.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=process.env.MODAL_CDP_URL||'http://127.0.0.1:9234',app='http://127.0.0.1:8883/';
 const page=await(await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 const clickText=async text=>ev(`[...document.querySelectorAll('#railTicketDetails button')].find(b=>b.textContent===${JSON.stringify(text)}).click()`);
 const get=path=>ev(`fetch(${JSON.stringify(path)}).then(r=>r.json())`);
 const upload=async file=>{const d=await call('DOM.getDocument');const n=await call('DOM.querySelector',{nodeId:d.root.nodeId,selector:'#railTicketFiles'});await call('DOM.setFileInputFiles',{nodeId:n.nodeId,files:[file]});await wait(`document.getElementById('railUploadProgress').hidden && document.getElementById('railTicketDetails').textContent.includes('Сотрудник не найден в базе данных')`);};
 try{
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:app});await wait(`typeof railEmployeeControls==='function' && typeof saveEmployeeData==='function'`);
  await ev(`document.getElementById('luvrNavButton').click();document.getElementById('railTicketsNavButton').click()`);
  await wait(`document.querySelectorAll('#railTicketList tr').length>0`);
  const initialEmployees=(await get('/api/employees')).items.length;
  await upload('C:/Projects/rail-employee-new.pdf');
  let tickets=(await get('/api/rail-tickets')).items;
  const ticket=tickets.find(t=>t.full_name==='СИДОРОВ СЕМЁН ПЕТРОВИЧ');assert.ok(ticket);const ticketCount=tickets.length;
  assert.equal(ticket.employee_id,null);assert.equal(ticket.movement_id,null);
  await clickText('Добавить сотрудника');await wait(`!document.getElementById('employeeModal').hidden`);
  assert.equal(await ev(`document.getElementById('employeeNameInput').value`),'Сидоров Семён Петрович');
  await ev(`document.getElementById('employeeModalCancel').click()`);
  assert.equal((await get('/api/rail-tickets/'+ticket.id)).item.movement_id,null);
  assert.equal((await get('/api/employees')).items.length,initialEmployees);
  await clickText('Добавить сотрудника');await wait(`!document.getElementById('employeeModal').hidden`);
  await ev(`document.getElementById('employeePositionSelect').value='1';document.getElementById('employeePositionSelect').dispatchEvent(new Event('change'));document.getElementById('employeePhoneInput').value='+7 900 123-45-67'`);
  // Simulate one server failure, then retry through the real existing POST API.
  await ev(`window.realEmployeeFetch=window.fetch;window.fetch=(url,options)=>{if(url==='/api/employees'&&options?.method==='POST'){window.fetch=window.realEmployeeFetch;return Promise.resolve(new Response(JSON.stringify({message:'Тестовая ошибка сохранения'}),{status:503,headers:{'Content-Type':'application/json'}}));}return window.realEmployeeFetch(url,options);};document.getElementById('employeeModalSave').click()`);
  await wait(`!document.getElementById('employeeModalSave').disabled && !document.getElementById('employeeModalError').hidden`);
  assert.equal(await ev(`document.getElementById('employeePhoneInput').value`),'+7 900 123-45-67');
  assert.equal(await ev(`document.getElementById('employeeNameInput').value`),'Сидоров Семён Петрович');
  assert.equal((await get('/api/rail-tickets/'+ticket.id)).item.status,'PARSED');
  await ev(`document.getElementById('employeeModalError').hidden=true`);
  fs.mkdirSync('C:/Projects/rail-employee-review',{recursive:true});
  const image=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync('C:/Projects/rail-employee-review/add-employee-1920x1080.png',Buffer.from(image.data,'base64'));
  await ev(`document.getElementById('employeeModalSave').click()`);await wait(`document.getElementById('employeeModal').hidden && document.querySelector('#railTicketDetails .ticket-confirm')`);
  const created=(await get('/api/employees')).items.find(e=>e.full_name==='Сидоров Семён Петрович');assert.ok(created);
  let refreshed=(await get('/api/rail-tickets/'+ticket.id)).item;assert.equal(refreshed.employee_id,created.id);assert.equal(refreshed.movement_id,null);
  await clickText('Подтвердить сотрудника');await wait(`document.getElementById('railTicketDetails').textContent.includes('Подтверждён')`);
  refreshed=(await get('/api/rail-tickets/'+ticket.id)).item;assert.equal(refreshed.status,'CONFIRMED');const mid=refreshed.movement_id;
  await ev(`fetch('/api/rail-tickets/${ticket.id}/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})`);
  // Reupload is a duplicate, with the same ticket and movement IDs.
  const d=await call('DOM.getDocument');const n=await call('DOM.querySelector',{nodeId:d.root.nodeId,selector:'#railTicketFiles'});
  await call('DOM.setFileInputFiles',{nodeId:n.nodeId,files:['C:/Projects/rail-employee-new.pdf']});await wait(`document.getElementById('railUploadProgress').hidden`);
  assert.equal((await get('/api/rail-tickets')).items.length,ticketCount);
  assert.equal((await get('/api/rail-tickets/'+ticket.id)).item.movement_id,mid);
  await ev(`window.confirm=()=>true`);await clickText('⊘  Аннулировать билет');await wait(`document.getElementById('railTicketDetails').textContent.includes('Восстановить билет')`);
  await clickText('Восстановить билет');await wait(`document.getElementById('railTicketDetails').textContent.includes('Подтверждён')`);
  assert.equal((await get('/api/rail-tickets/'+ticket.id)).item.movement_id,mid);
  await upload('C:/Projects/rail-employee-similar.pdf');
  assert.equal(await ev(`document.getElementById('railEmployeeSelect').value`),'');
  assert.ok(await ev(`document.getElementById('railTicketDetails').textContent.includes('похожие ФИО')`));
  const similar=(await get('/api/rail-tickets')).items.find(t=>t.full_name==='ИВАНОВ ИВАН ИВАНОВИЧ');
  assert.equal(similar.movement_id,null);
  // Existing name in the creation form offers selection, never creates a duplicate.
  await clickText('Добавить сотрудника');await wait(`!document.getElementById('employeeModal').hidden`);
  await ev(`document.getElementById('employeeNameInput').value='  ИВАНОВ  ИВАН ПЕТРОВИЧ ';document.getElementById('employeePositionSelect').value='1';document.getElementById('employeeModalSave').click()`);
  await wait(`document.querySelector('#employeeTicketMatches button') && !document.getElementById('employeeModalSave').disabled`);
  assert.equal((await get('/api/employees')).items.length,initialEmployees+1);
  await ev(`document.querySelector('#employeeTicketMatches button').click()`);
  await wait(`document.getElementById('employeeModal').hidden && document.getElementById('railEmployeeSelect')?.value`);
  const selected=Number(await ev(`document.getElementById('railEmployeeSelect').value`));
  await wait(`[...document.querySelectorAll('#railTicketDetails button')].some(b=>b.textContent==='Подтвердить выбранного сотрудника'&&!b.disabled)`);
  await clickText('Подтвердить выбранного сотрудника');await wait(`document.getElementById('railTicketDetails').textContent.includes('Подтверждён')`);
  assert.equal((await get('/api/rail-tickets/'+similar.id)).item.employee_id,selected);
  assert.deepEqual(errors,[]);
  console.log('PASS: upload, missing employee, existing modal prefill, cancel, save failure/retry, create/link/confirm, similar names/manual choice, duplicate creation prevention, repeat upload, annul/restore; no JS exceptions');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
