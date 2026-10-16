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
  await wait('typeof openPositionModal==="function"');
  await ev('document.getElementById("employeesNavButton").click();document.getElementById("positionsTab").click()');
  await wait('positionItems.length>0');
  assert.equal(await ev('document.querySelectorAll("#positionRequiresDailyReportInput").length'),1);
  await ev('document.getElementById("addPositionButton").click();positionNameInput.value="Browser report flag 2";positionRequiresDailyReportInput.value="true";positionPlannedCountInput.value="12";positionModalSave.click()');
  await wait('positionItems.some(p=>p.name==="Browser report flag 2")');
  const created=await ev('positionItems.find(p=>p.name==="Browser report flag 2")');
  assert.equal(created.requires_daily_report,true);assert.equal(created.planned_count,12);
  await call('Page.reload');await wait('typeof openPositionModal==="function"');
  await ev('document.getElementById("employeesNavButton").click();document.getElementById("positionsTab").click()');
  await wait('positionItems.some(p=>p.name==="Browser report flag 2")');
  await ev(`document.querySelector('.edit-position[data-id="${created.id}"]').click()`);
  assert.equal(await ev('positionRequiresDailyReportInput.value'),'true');assert.equal(await ev('positionPlannedCountInput.value'),'12');
  await ev('positionRequiresDailyReportInput.value="false";positionPlannedCountInput.value="7";positionModalSave.click()');
  await wait('positionItems.find(p=>p.name==="Browser report flag 2")?.requires_daily_report===false');
  await call('Page.reload');await wait('typeof openPositionModal==="function"');
  await ev('document.getElementById("employeesNavButton").click();document.getElementById("positionsTab").click()');
  await wait('positionItems.some(p=>p.name==="Browser report flag 2")');
  await ev(`document.querySelector('.edit-position[data-id="${created.id}"]').click()`);
  assert.equal(await ev('positionRequiresDailyReportInput.value'),'false');assert.equal(await ev('positionPlannedCountInput.value'),'7');assert.ok(await ev("[...document.querySelectorAll('.position-planned-count')].some(x=>x.textContent==='7')"));
  await ev('closePositionModal()');
  await ev(`document.querySelector('.edit-position[data-id="${created.id}"]').closest('.position-table-row').querySelector('.position-count-button').click()`);
  assert.equal(await ev('positionModal.hidden'),true);
  await ev(`(()=>{const input=document.querySelector('.position-planned-count input');input.value='19';input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()`);
  await wait('positionItems.find(p=>p.name==="Browser report flag 2")?.planned_count===19');
  await ev('loadPositions()');
  assert.equal(await ev('positionItems.find(p=>p.name==="Browser report flag 2").planned_count'),19);
  await ev(`document.querySelector('.edit-position[data-id="${created.id}"]').closest('.position-table-row').querySelector('.position-count-button').click()`);
  await ev(`(()=>{const input=document.querySelector('.position-planned-count input');input.value='25';input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));})()`);
  assert.equal(await ev('positionItems.find(p=>p.name==="Browser report flag 2").planned_count'),19);
  assert.deepEqual(errors,[]);
  console.log('PASS: existing position form, create Yes, reload Yes, change No, reload No; no JS errors');

 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
