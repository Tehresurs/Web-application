const assert=require('node:assert/strict');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+expression);};
 try{
  await call('Runtime.enable');await call('Page.navigate',{url:'http://127.0.0.1:8881/'});
  await wait('typeof railRequest==="function"');
  await ev('document.getElementById("railTicketsNavButton").click();window.confirm=()=>true;window.ticketChanges=[];document.addEventListener("luvr-ticket-state-changed",e=>ticketChanges.push(e.detail))');
  await wait('document.querySelector(".ticket-annul-button")!=null');
  const before=await ev("railRequest('/api/rail-tickets').then(x=>x.items[0])");assert.equal(before.status,'CONFIRMED');
  const calendar=()=>ev(`railRequest('/api/employees/${before.employee_id}/luvr/calendar?year=2026&month=10').then(x=>x.item)`);
  const initial=await calendar();
  await ev('document.querySelector(".ticket-annul-button").click()');await wait('document.querySelector(".ticket-annul-button")?.textContent==="Восстановить билет"');
  assert.notDeepEqual(await calendar(),initial);
  await wait('!document.querySelector(".ticket-annul-button").disabled');
  await ev('document.querySelector(".ticket-annul-button").click()');await wait('document.querySelector(".ticket-annul-button")?.textContent.includes("Аннулировать билет")');
  const after=await ev(`railRequest('/api/rail-tickets/${before.id}').then(x=>x.item)`);
  assert.equal(after.status,'CONFIRMED');assert.equal(after.movement_id,before.movement_id);assert.equal(after.file_hash,before.file_hash);
  assert.deepEqual(await calendar(),initial);assert.equal(await ev('ticketChanges.length'),2);assert.deepEqual(errors,[]);
  console.log('PASS: annul/restore button, preserved ticket and movement IDs, restored LUVR calendar, refresh events, no JS errors');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
