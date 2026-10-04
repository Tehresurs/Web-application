const assert=require('node:assert/strict');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json();const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
 const click=id=>ev(`document.getElementById('${id}').click()`),ready=()=>wait('!document.getElementById("luvrMonthRefresh").disabled');
 const value=key=>`document.querySelector('#luvrMonthTotals [data-day-total="${key}"] [data-total-date="2026-10-01"]').textContent`;
 try{
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:'http://127.0.0.1:8881/'});await wait('typeof renderLuvrDayTotals==="function"');await click('luvrNavButton');await ready();
  assert.equal(await ev('document.getElementById("luvrMonthTotals").children.length'),0);await click('luvrMonthForm');await ready();
  assert.equal(await ev('document.getElementById("luvrMonthTotals").children.length'),1);assert.equal(await ev(value('work_equivalent')),'1');
  const before=await ev('document.getElementById("luvrMonthTotals").textContent');await ev('document.querySelector("[data-sort=full_name]").click()');assert.equal(await ev('document.getElementById("luvrMonthTotals").textContent'),before);
  for(const left of [0,2000]){
   await ev(`document.querySelector('.luvr-month-scroll').scrollLeft=${left}`);
   const aligned=await ev(`(()=>{const row=document.querySelector('#luvrMonthBody tr');return Array.from(row.querySelectorAll('[data-date]')).every(b=>{const td=b.parentElement,total=document.querySelector('#luvrMonthTotals [data-day-total="work_equivalent"] [data-total-date="'+b.dataset.date+'"]');return Math.abs(td.getBoundingClientRect().left-total.getBoundingClientRect().left)<1;});})()`);assert.ok(aligned);
  }
  await ev(`document.querySelector('#luvrMonthBody tr[data-employee="3"] [data-date="2026-10-01"]').click()`);
  await ev('document.getElementById("luvrMonthValue").value="DOWNTIME";document.getElementById("luvrMonthEditor").requestSubmit()');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();
  assert.equal(await ev(value('work_equivalent')),'0');assert.equal(await ev(value('work_equivalent')),'0');
  await ev(`document.querySelector('#luvrMonthBody tr[data-employee="3"] [data-date="2026-10-01"]').click()`);await click('luvrMonthRestore');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();assert.equal(await ev('document.getElementById("luvrMonthTotals").textContent'),before);
  for(const [year,month,days] of [[2026,2,28],[2024,2,29],[2026,4,30]]){
   await ev(`document.getElementById('luvrMonthYear').value=${year};document.getElementById('luvrMonthNumber').value=${month};document.getElementById('luvrMonthNumber').dispatchEvent(new Event('change'))`);await ready();await click('luvrMonthForm');await ready();
   assert.equal(await ev('document.querySelector("#luvrMonthTotals tr").querySelectorAll("[data-total-date]").length'),days);
  }
  assert.deepEqual(errors,[]);console.log('PASS: final day totals, membership, sorting invariant, aligned columns before/after horizontal scroll, override/reset, 28/29/30/31 days');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
