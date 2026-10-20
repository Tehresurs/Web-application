// UI-only DK scenario: all PUT/DELETE requests are intercepted in this tab.
const assert=require('node:assert/strict');
(async()=>{
 const cdp=process.env.MODAL_CDP_URL||'http://127.0.0.1:9234';
 const app='http://127.0.0.1:8001/';
 const page=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let n=0;n<200;n++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 try{
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Page.navigate',{url:app});
  await wait("typeof ProductionMatrixController!=='undefined' && document.getElementById('productionMatrixNavButton')");
  await ev(`(async()=>{
   const real=await fetch('/api/production-matrix?year=2026&month=10').then(r=>r.json());
   const employee=real.item.employees.find(e=>e.dk_eligible_position && e.luvr_days.some(d=>['FULL','HALF'].includes(d.final_code)));
   if(!employee)throw Error('No eligible employee for read-only UI scenario');
   const day=employee.luvr_days.find(d=>['FULL','HALF'].includes(d.final_code)).date;
   window.dkUi={original:real,employee,day,active:false,leader:true,writes:[]};
   const originalFetch=window.fetch.bind(window);
   window.fetch=async(input,options={})=>{
    const url=String(input),method=(options.method||'GET').toUpperCase();
    if(url.includes('/production-matrix/dk/')){
     window.dkUi.writes.push(method);window.dkUi.active=method==='PUT';
     return new Response(JSON.stringify({status:'ok',item:{}}),{headers:{'Content-Type':'application/json'}});
    }
    if(method!=='GET')throw Error('UI test blocks all other writes');
    if(url.startsWith('/api/production-matrix?')){
     const m=structuredClone(window.dkUi.original);
     m.item.employees=m.item.employees.filter(e=>e.employee_id===window.dkUi.employee.employee_id);
     m.item.capabilities={can_manage_dk:window.dkUi.leader};
     const e=m.item.employees[0];e.dk_dates=window.dkUi.active?[window.dkUi.day]:[];
     const c=e.checks.find(c=>c.date===window.dkUi.day);
     c.is_dk=window.dkUi.active;c.dk_cents=window.dkUi.active?c.available_cents:0;
     if(window.dkUi.active){
      e.rows=[{row_key:'ui-dk',kind:'OBJECT',total_cents:0,cells:{[window.dkUi.day]:{
       date:window.dkUi.day,employee_id:e.employee_id,source:'PLAN',share_cents:0,status:'OK',warnings:[],
       is_dk:true,comment:'Проведен ДК',object_name:'UI test',control_mode:'INSPECTION'}}}];
     }
     return new Response(JSON.stringify(m),{headers:{'Content-Type':'application/json'}});
    }
    return originalFetch(input,options);
   };
   document.getElementById('pmMonth').value='2026-10';
   document.getElementById('productionMatrixNavButton').click();
  })()`);
  const loaded="!document.getElementById('pmRefresh').disabled && document.querySelectorAll('#pmTable .pm-employee').length===1";
  const choose="document.querySelector('#pmTable .pm-employee [data-date=\"'+window.dkUi.day+'\"]').click()";
  const button=text=>`[...document.querySelectorAll('#pmDetails button')].find(b=>b.textContent===${JSON.stringify(text)})`;
  await wait(loaded);await ev(choose);
  assert.equal(await ev(`Boolean(${button('Назначить ДК')})`),true);
  await ev(button('Назначить ДК')+'.click()');
  await wait(loaded+" && window.dkUi.active");
  await ev(choose);
  assert.equal(await ev("document.getElementById('pmDetails').textContent.includes('0 ДК · Проведен ДК')"),true);
  assert.equal(await ev("document.querySelector('#pmTable .pm-employee [data-date=\"'+window.dkUi.day+'\"]').textContent"),'0 ДК');
  assert.equal(await ev("document.querySelectorAll('#pmTable .pm-dk').length>0"),true);
  await ev(button('Отменить ДК')+'.click()');await wait(loaded+" && !window.dkUi.active");
  await ev(choose);assert.equal(await ev(`Boolean(${button('Назначить ДК')})`),true);
  for(const active of [false,true]){
   await ev("window.dkUi.leader=false;window.dkUi.active="+active+";document.getElementById('pmRefresh').click()");
   await wait(loaded);await ev(choose);
   assert.equal(await ev("[...document.querySelectorAll('#pmDetails button')].some(b=>['Назначить ДК','Отменить ДК'].includes(b.textContent))"),false);
  }
  assert.deepEqual(await ev('window.dkUi.writes'),['PUT','DELETE']);
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log('PASS: leader assign/cancel, 0 DK styling/comment, viewer read-only; all writes intercepted, no server data changed.');
 }finally{
  ws.close();await fetch(cdp+'/json/close/'+page.id);
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
