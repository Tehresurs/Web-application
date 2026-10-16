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
  await ev('document.getElementById("addPositionButton").click();positionNameInput.value="Equipment browser";positionEquipmentInput.value="VIK\\nRuler\\nTape";positionReportDescriptionInput.value="Report unchanged";positionAosDescriptionInput.value="AOS unchanged";positionModalSave.click()');
  await wait('positionItems.some(p=>p.name==="Equipment browser")');
  const item=await ev('positionItems.find(p=>p.name==="Equipment browser")');
  assert.equal(item.equipment_description,'VIK\nRuler\nTape');
  await call('Page.reload');await wait('typeof openPositionModal==="function"');
  await ev('document.getElementById("employeesNavButton").click();document.getElementById("positionsTab").click()');
  await wait('positionItems.some(p=>p.name==="Equipment browser")');
  await ev(`openPositionModal(positionItems.find(p=>p.id===${item.id}))`);
  assert.equal(await ev('positionEquipmentInput.value'),'VIK\nRuler\nTape');
  await ev('positionEquipmentInput.value="Level\\nTool";positionModalSave.click()');
  await wait('positionItems.find(p=>p.name==="Equipment browser")?.equipment_description==="Level\\nTool"');
  await ev('loadPositions()');
  const edited=await ev('positionItems.find(p=>p.name==="Equipment browser")');
  assert.equal(edited.report_description,'Report unchanged');assert.equal(edited.aos_description,'AOS unchanged');
  await ev(`openPositionModal(positionItems.find(p=>p.id===${item.id}));positionEquipmentInput.value="";positionModalSave.click()`);
  await wait('positionItems.find(p=>p.name==="Equipment browser")?.equipment_description===""');
  assert.deepEqual(errors,[]);
  console.log('PASS equipment: create multiline, reload, edit, blank, other descriptions preserved; no JS errors');

 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
