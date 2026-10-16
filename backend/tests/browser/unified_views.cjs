// Read-only browser verification against the running application.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=process.env.MODAL_CDP_URL||'http://127.0.0.1:9234';
 const page=await(await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 try{
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Page.navigate',{url:process.env.MODAL_APP_URL||'http://127.0.0.1:8000/'});
  await wait(`typeof renderCrewWorkspace==='function'`);
  await ev(`document.getElementById('crewsNavButton').click()`);
  if(process.env.UI_WRITE_TEST==='1'){
   assert.equal(new URL(process.env.MODAL_APP_URL).port,'8881');
   await ev(`document.getElementById('addCrewButton').click();crewDriverInput.value='UI Crew';crewPhoneInput.value='12345';crewVehicleInput.value='Car';crewPlateInput.value='Plate';crewModalSave.click()`);
   await wait(`crewItems.some(c=>c.driver_full_name==='UI Crew') && document.getElementById('crewModal').hidden`);
   await ev(`document.querySelector('#crewList [data-record-id="'+crewItems.find(c=>c.driver_full_name==='UI Crew').id+'"]').click();document.querySelector('#crewList .edit-crew').click();crewPhoneInput.value='54321';crewModalSave.click()`);
   await wait(`crewItems.some(c=>c.driver_full_name==='UI Crew'&&c.driver_phone==='54321')`);
  }
  await wait(`document.querySelector('#crewList .directory-choice')`);
  await ev(`document.querySelector('#crewList .directory-choice').click();document.querySelector('#crewList .edit-crew').click()`);
  assert.equal(await ev(`document.getElementById('crewModal').hidden`),false);
  await ev(`document.getElementById('crewModalCancel').click();document.getElementById('crewSearchInput').value='unlikely-no-result-123';document.getElementById('crewSearchInput').dispatchEvent(new Event('input'))`);
  assert.equal(await ev(`document.querySelectorAll('#crewList .directory-choice').length`),0);
  await ev(`document.getElementById('crewSearchInput').value='';document.getElementById('crewSearchInput').dispatchEvent(new Event('input'))`);
  assert.ok(await ev(`document.querySelectorAll('#crewList .directory-choice').length`)>0);
  await ev(`document.getElementById('objectsNavButton').click()`);
  await wait(`document.querySelector('#objectList .directory-choice')`);
  await ev(`document.querySelector('#objectList .directory-choice').click();document.querySelector('#objectList .edit-object-directory').click()`);
  assert.equal(await ev(`document.getElementById('objectDirectoryModal').hidden`),false);
  await ev(`document.getElementById('objectDirectoryModalCancel').click();document.getElementById('objectSearchInput').value='unlikely-no-result-123';document.getElementById('objectSearchInput').dispatchEvent(new Event('input'))`);
  assert.equal(await ev(`document.querySelectorAll('#objectList .directory-choice').length`),0);
  await ev(`document.getElementById('objectSearchInput').value='';document.getElementById('objectSearchInput').dispatchEvent(new Event('input'));document.querySelector('#objectList .object-tree-actions button').click()`);
  assert.equal(await ev(`document.getElementById('subobjectDirectoryModal').hidden`),false);
  await ev(`document.getElementById('subobjectDirectoryCancel').click()`);
  if(process.env.UI_WRITE_TEST==='1'){
   await ev(`document.getElementById('addDirectoryObjectButton').click();objectDirectoryNameInput.value='UI Object';objectDirectoryModalSave.click()`);
   await wait(`objectItems.some(o=>o.name==='UI Object') && document.getElementById('objectDirectoryModal').hidden`);
   await ev(`document.querySelector('#objectList [data-record-id="'+objectItems.find(o=>o.name==='UI Object').id+'"]').click();document.querySelector('#objectList .edit-object-directory').click();objectDirectoryNameInput.value='UI Object Edited';objectDirectoryModalSave.click()`);
   await wait(`objectItems.some(o=>o.name==='UI Object Edited')`);
   await ev(`document.querySelector('#objectList [data-record-id="'+objectItems.find(o=>o.name==='UI Object Edited').id+'"]').click();document.querySelector('#objectList .object-tree-actions button').click();document.getElementById('subobjectDirectoryName').value='UI Child';document.getElementById('subobjectDirectoryForm').requestSubmit()`);
   await wait(`document.getElementById('subobjectDirectoryModal').hidden && objectSubobjects.some(s=>s.name==='UI Child')`);
   await ev(`document.querySelector('#objectList .object-tree-child button').click();document.getElementById('subobjectDirectoryParent').value=String(objectItems.find(o=>o.name!=='UI Object Edited').id);document.getElementById('subobjectDirectoryForm').requestSubmit()`);
   await wait(`document.getElementById('subobjectDirectoryModal').hidden`);
   assert.equal(await ev(`objectSubobjects.find(s=>s.name==='UI Child').object_id===objectItems.find(o=>o.name==='UI Object Edited').id`),false);
  }
  for(const [id,name] of [['crewsNavButton','crews'],['objectsNavButton','objects'],['processingNavButton','processing']]){
   await ev(`document.getElementById('${id}').click()`);
   if(name==='processing'){
    await ev(`folderPath.value='C:/Projects/ui-word-review';folderPath.dispatchEvent(new Event('change'))`);
    await wait(`!parseButton.disabled`);
    await ev(`parseButton.click()`);
    await wait(`!parseButton.disabled && window.processingReports.length===2`);
    assert.ok(await ev(`window.processingReports.some(r=>r.status==='error')`));
    await ev(`document.querySelector('#resultTable .view-button').click()`);
    assert.ok(await ev(`document.getElementById('detailsPanel').classList.contains('open') || document.getElementById('detailsPanel').classList.contains('active') || !document.getElementById('detailsPanel').hidden`));
    await ev(`closeDetails()`);
    await wait(`document.getElementById('detailsOverlay').hidden`);
   }
   for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
    await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
    assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'),name+' page overflow');
    fs.mkdirSync('C:/Projects/unified-ui-review',{recursive:true});
    fs.writeFileSync(`C:/Projects/unified-ui-review/${name}-${width}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
   }
  }
  await ev(`document.getElementById('employeesNavButton').click()`);
  await wait(`document.querySelector('#employeeList tbody tr')`);
  assert.equal(await ev(`getComputedStyle(document.getElementById('crewList')).display==='none' || document.getElementById('crewsPage').hidden`),true);
  assert.deepEqual(errors,[]);console.log('PASS crew and object search, selection, dialogs, empty states, subobject form');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
