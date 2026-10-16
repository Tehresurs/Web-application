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
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:app});await wait(`typeof document.getElementById('productionMatrixNavButton')?.onclick==='function'`);
  await click('#luvrNavButton');await click('#productionMatrixNavButton');
  await ev(`document.getElementById('pmMonth').value='2026-10';document.getElementById('pmMonth').dispatchEvent(new Event('change'))`);await loaded();
  assert.equal(await ev(`document.getElementById('pmError').hidden`),true);
  const data=await matrix();const employee=write?data.employees.find(e=>e.full_name==='Matrix browser employee'):
   data.employees.find(e=>e.requires_daily_report===false&&e.rows.length&&e.rows.every(r=>r.kind==='CAMERAL'))||data.employees.find(e=>e.rows.length);
  assert.ok(employee);const eid=employee.employee_id;
  const nameSelector=`.pm-employee[data-employee="${eid}"] .pm-name button`;
  await click(nameSelector);assert.equal(await ev(`document.querySelector(${JSON.stringify(nameSelector)}).getAttribute('aria-expanded')`),'true');
  await click(nameSelector);assert.equal(await ev(`document.querySelectorAll('.pm-inner').length`),0);await click(nameSelector);
  const choose=async(day,kind)=>{
   const d=await matrix(),e=d.employees.find(e=>e.employee_id===eid);
   const row=e.rows.find(r=>r.cells[day]&&(!kind||r.cells[day].kind===kind));assert.ok(row,day);
   await ev(`(()=>{const row=[...document.querySelectorAll('.pm-inner tr[data-row-key]')].find(r=>r.dataset.rowKey===${JSON.stringify(row.row_key)});row.querySelector('[data-date="${day}"]').click()})()`);
   assert.equal(await ev(`document.getElementById('pmDetails').hidden`),false);return row;
  };
  const firstDay=Object.keys(employee.rows[0].cells)[0];await choose(firstDay);
  await ev(`document.querySelector(${JSON.stringify(nameSelector)}).closest('tr').scrollIntoView({block:'nearest'})`);
  if(write){
   assert.equal(employee.rows.filter(r=>r.cells['2026-10-03']).length,3);
   assert.deepEqual(employee.rows.filter(r=>r.cells['2026-10-03']).map(r=>r.cells['2026-10-03'].share_cents),[33,33,34]);
   const edit=async(day,field,value)=>{
    await choose(day,'OBJECT');
    await ev(`(()=>{const s=document.querySelector('.pm-inner select[data-field="${field}"]');s.value=${JSON.stringify(String(value))};s.dispatchEvent(new Event('change'))})()`);
    await loaded();assert.equal(await ev(`document.getElementById('pmError').hidden`),true);
   };
   await edit('2026-10-03','CATEGORY',90);await edit('2026-10-04','CONTROL_MODE','OPERATIONAL');
   await click('#pmRefresh');await loaded();
   let d=(await matrix()).employees.find(e=>e.employee_id===eid);
   let c=d.rows.find(r=>r.cells['2026-10-05']?.object_id===1).cells['2026-10-05'];
   assert.equal(c.category_id,90);assert.equal(c.control_mode,'OPERATIONAL');
   c=d.rows.find(r=>r.cells['2026-10-03']?.object_id===1).cells['2026-10-03'];assert.equal(c.control_mode,'INSPECTION');
   await edit('2026-10-06','CONTROL_MODE','INSPECTION');
   d=(await matrix()).employees.find(e=>e.employee_id===eid);
   assert.equal(d.rows.find(r=>r.cells['2026-10-06']?.object_id===1).cells['2026-10-06'].source,'FACT');
   assert.equal(d.rows.find(r=>r.cells['2026-10-07']?.object_id===1).cells['2026-10-07'].control_mode,null);
   await choose('2026-10-10','CAMERAL');assert.equal(await ev(`document.querySelectorAll('.pm-inner select').length`),0);
   assert.ok(await ev(`document.getElementById('pmDetails').textContent.includes('Камеральный контроль')`));
   await choose('2026-10-15','OBJECT');assert.ok(await ev(`document.querySelector('#pmDetails .pm-check-CONFLICT')!==null`));
   assert.ok(await ev(`document.getElementById('pmDetails').textContent.includes('Подтверждённый факт')`));
   assert.ok(await ev(`document.querySelectorAll('.pm-check-WARNING').length>0`));
   // Reload the whole page: persisted corrections must still render from the API.
   await ev('window.__matrixOldPage=true');
   await call('Page.reload',{ignoreCache:true});await wait(`!window.__matrixOldPage && typeof document.getElementById('productionMatrixNavButton')?.onclick==='function'`);
   await click('#luvrNavButton');await click('#productionMatrixNavButton');
   await ev(`document.getElementById('pmMonth').value='2026-10';document.getElementById('pmMonth').dispatchEvent(new Event('change'))`);await loaded();await click(nameSelector);
   await choose('2026-10-05','OBJECT');assert.equal(await ev(`document.querySelector('[data-field="CATEGORY"]').value`),'90');
   assert.equal(await ev(`document.querySelector('[data-field="CONTROL_MODE"]').value`),'OPERATIONAL');
   if(process.env.PM_GEODETIC_TEST==='1'){
    assert.ok(await ev(`!!document.querySelector('[data-field="CONTROL_MODE"] option[value="GEODETIC"]')`));
    await edit('2026-10-05','CONTROL_MODE','GEODETIC');
    await click('#pmRefresh');await loaded();await choose('2026-10-05','OBJECT');
    assert.equal(await ev(`document.querySelector('[data-field="CONTROL_MODE"]').value`),'GEODETIC');
    assert.ok(await ev(`document.getElementById('pmDetails').textContent.includes('Геодезический контроль')`));
    const created=await ev(`(async()=>{const h=(await(await fetch('/api/employees/${eid}/production-assignments?date_from=2026-10-01&date_to=2026-10-31')).json()).item;const r=await fetch('/api/employees/${eid}/production-assignments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({effective_from:'2026-10-20',arrival_movement_ref:h.history[0].arrival_movement_ref,assignment_state:'OBJECTS',items:[{object_id:3,po_id:1,initial_category_id:1}]})});return {status:r.status,body:await r.json(),defaultMode:h.default_control_mode};})()`);
    assert.equal(created.status,200,JSON.stringify(created));assert.equal(created.defaultMode,'GEODETIC');
    assert.equal(created.body.item.items[0].initial_control_mode,'GEODETIC');
    await click('#pmRefresh');await loaded();await choose('2026-10-21','OBJECT');
    assert.equal(await ev(`document.querySelector('[data-field="CONTROL_MODE"]').value`),'GEODETIC');
   }
   const office=(await matrix()).employees.find(e=>e.requires_daily_report===false);
   assert.ok(office);assert.ok(office.totals.cameral_cents>0);
   assert.equal(office.totals.cameral_cents,office.totals.available_cents);
   const cameral=office.rows.find(r=>r.kind==='CAMERAL');assert.ok(cameral);
   const day=Object.keys(cameral.cells)[0];
   assert.equal(cameral.cells[day].basis_kind,'POSITION_RULE');
   await click(`.pm-employee[data-employee="${office.employee_id}"] .pm-name button`);
   await ev(`(()=>{const row=[...document.querySelectorAll('.pm-inner tr[data-row-key]')].find(r=>r.dataset.rowKey===${JSON.stringify(cameral.row_key)});row.querySelector('[data-date="${day}"]').click()})()`);
   assert.ok(await ev(`document.getElementById('pmDetails').textContent.includes('По настройке должности')`));
   assert.ok(await ev(`document.querySelector('.pm-inner-scroll[data-employee="${office.employee_id}"] tfoot').textContent.includes('Камеральное время')`));
  }
  for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   const dimensions=await ev(`({page:document.documentElement.scrollWidth,viewport:innerWidth,table:document.getElementById('pmScroll').scrollWidth})`);
   assert.ok(dimensions.page<=width+1,JSON.stringify(dimensions));
   assert.ok(await ev(`(()=>{const outer=document.getElementById('pmScroll');outer.scrollLeft=250;
    const main=document.querySelector('.pm-table>thead th:nth-child(3)').getBoundingClientRect();
    return [...document.querySelectorAll('.pm-inner-scroll')].every(n=>getComputedStyle(n).overflowX==='visible'&&
      Math.abs(n.querySelector('thead th:nth-child(6)').getBoundingClientRect().left-main.left)<2);
   })()`),'One scroll owner and aligned calendar columns');
   await ev(`document.getElementById('pmScroll').scrollLeft=0`);
   fs.mkdirSync('C:/Projects/production-matrix-ui-review',{recursive:true});
   const shot=await call('Page.captureScreenshot',{format:'png'});
   fs.writeFileSync(`C:/Projects/production-matrix-ui-review/${write?'fixture':'working'}-${width}x${height}.png`,Buffer.from(shot.data,'base64'));
  }
  await click('#pmNext');await wait(`!document.getElementById('pmRefresh').disabled`);
  assert.equal(await ev(`document.getElementById('pmMonth').value`),'2026-11');
  await click('#pmPrevious');await loaded();
  for(const tab of ['railTicketsNavButton','luvrMonthNavButton','luvrCalendarNavButton']){
   await click('#'+tab);assert.equal(await ev(`getComputedStyle(document.getElementById('productionMatrixPage')).display`),'none');
  }
  await click('#productionMatrixNavButton');await loaded();
  assert.equal(await ev(`getComputedStyle(document.getElementById('railTicketsPage')).display`),'none');
  for(const tab of ['processingNavButton','employeesNavButton','objectsNavButton','crewsNavButton','journalNavButton','logsNavButton']){
   await click('#'+tab);assert.equal(await ev(`getComputedStyle(document.getElementById('productionMatrixPage')).display`),'none');
   assert.equal(await ev(`getComputedStyle(document.getElementById('railTicketsPage')).display`),'none');
  }
  assert.deepEqual(errors,[]);
  console.log('PASS matrix browser:',write?'isolated CRUD / inheritance / FACT / CAMERAL / conflict / reload':'working data, read only','; months, expansion, details, navigation, three viewports, no JS exceptions');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
