// Read-only on the working app. PM_WRITE_TEST=1 requires the isolated fixture server.
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const base=process.env.MODAL_CDP_URL||'http://127.0.0.1:9234';
 const app=process.env.MODAL_APP_URL||'http://127.0.0.1:8000/';
 const write=process.env.PM_WRITE_TEST==='1';
 if(write)assert.equal(new URL(app).port,'8882','Writes restricted to the isolated fixture');
 const page=await(await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 const click=async selector=>ev(`document.querySelector(${JSON.stringify(selector)}).click()`);
 const loaded=()=>wait(`!document.getElementById('pmRefresh').disabled && document.querySelectorAll('.pm-employee').length>0`);
 const matrix=()=>ev(`fetch('/api/production-matrix?year=2026&month=10').then(r=>r.json()).then(r=>r.item)`);
 try{
  assert.ok(write,'Use isolated fixture with PM_WRITE_TEST=1');
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Page.navigate',{url:app});await wait(`typeof initProductionMatrix==='function'`);
  await click('#employeesNavButton');await wait(`document.querySelectorAll('#employeeList tbody tr').length>0`);
  const eid=Number(fs.readFileSync('C:/Projects/matrix-ui-browser-employee.txt','utf8'));
  await click(`#employeeList tr[data-employee="${eid}"]`);
  const root='.employee-personal-matrix', ready=`document.querySelector('${root} .pm-employee') && !document.querySelector('${root} [data-pm-id="pmRefresh"]').disabled`;
  await wait(ready);
  assert.deepEqual(await ev(`[...document.querySelectorAll('${root} .pm-employee')].map(r=>Number(r.dataset.employee))`),[eid]);
  assert.equal(await ev(`document.querySelectorAll('[id="pmTable"]').length`),1);
  await click(`${root} .pm-inner [data-date="2026-10-02"]`);
  await wait(`document.querySelector('${root} [data-field="CONTROL_MODE"]')`);
  await ev(`(()=>{const s=document.querySelector('${root} [data-field="CONTROL_MODE"]');s.value='OPERATIONAL';s.dispatchEvent(new Event('change'));})()`);
  await wait(ready);
  assert.equal(await ev(`document.querySelector('${root} [data-field="CONTROL_MODE"]').value`),'OPERATIONAL');
  await click(`${root} [data-pm-id="pmRefresh"]`);await wait(ready);
  await click(`${root} .pm-inner [data-date="2026-10-02"]`);
  assert.equal(await ev(`document.querySelector('${root} [data-field="CONTROL_MODE"]').value`),'OPERATIONAL');
  await click(`${root} [data-pm-id="pmNext"]`);
  await wait(`!document.querySelector('${root} [data-pm-id="pmRefresh"]').disabled`);
  assert.equal(await ev(`document.querySelector('${root} [data-pm-id="pmMonth"]').value`),'2026-11');
  await click(`${root} [data-pm-id="pmPrevious"]`);await wait(ready);
  await click('.employee-card-movements [data-kind="movements"] > button');
  assert.equal(await ev('document.getElementById("employeeModal").hidden'),true);
  await ev(`(()=>{const f=document.querySelector('.employee-card-movements form');f.elements.movement_type.value='DEPARTURE';f.elements.date.value='2026-10-25';f.elements.time.value='15:00';f.requestSubmit();})()`);
  await wait(`!document.querySelector('.employee-card-movements form') && document.querySelector('.employee-card-movements')?.textContent.includes('25.10.2026')`);
  await wait(ready);
  const movements=await ev(`fetch('/api/employees/${eid}/luvr/movements').then(r=>r.json()).then(x=>x.items)`);
  const added=movements.find(m=>m.event_datetime.startsWith('2026-10-25'));assert.ok(added);
  await ev(`document.querySelector('.employee-card-movements [data-id="${added.id}"] button').click()`);
  await ev(`(()=>{const f=document.querySelector('.employee-card-movements form');f.elements.date.value='2026-10-26';f.requestSubmit();})()`);
  await wait(`!document.querySelector('.employee-card-movements form') && document.querySelector('.employee-card-movements')?.textContent.includes('26.10.2026')`);
  await wait(ready);
  for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'));
   await ev(`document.querySelector('${root}').scrollIntoView({block:'start'})`);
   fs.mkdirSync('C:/Projects/employee-sections-review',{recursive:true});
   fs.writeFileSync(`C:/Projects/employee-sections-review/${width}x${height}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  }
  await ev(`Array.from(document.querySelectorAll('${root} button')).find(b=>b.textContent==='Открыть полную матрицу').click()`);
  await wait(`!document.getElementById('productionMatrixPage').hidden && document.querySelector('#pmTable .pm-employee')`);
  assert.equal(await ev(`document.getElementById('pmMonth').value`),'2026-10');
  assert.deepEqual(errors,[]);
  console.log('PASS personal matrix: shared renderer, employee filter, override/reload, month, full view; inline movement create/edit; three viewports');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
