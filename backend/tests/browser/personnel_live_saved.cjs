// Live smoke: no login, no account creation, only anonymous rejected HR writes.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
(async()=>{
 const out=fs.readFileSync('backend/output/security/personnel_local_current.txt','utf8').trim();const cfg=JSON.parse(fs.readFileSync(path.join(out,'live_test_fixture.json'),'utf8'));
 const server=require('node:net').createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;await new Promise(r=>server.close(r));
 const chrome=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port,'--user-data-dir='+path.join(out,'readonly-browser-profile'),'about:blank'],{windowsHide:true,stdio:'ignore'});
 let ws;const result={success:false,accounts_created:false};let stage='load';
 try{
  let pages;for(let i=0;i<100;i++){try{pages=await(await fetch('http://127.0.0.1:'+port+'/json')).json();break}catch{}await new Promise(r=>setTimeout(r,100));}
  ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
  let seq=0;const pending=new Map(),errors=[];ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
  const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value};
  const wait=async expression=>{for(let i=0;i<160;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Browser readiness timeout '+JSON.stringify(await ev(`(()=>({error:document.querySelector('.personnel-dialog .ui-error')?.textContent,invalid:[...document.querySelectorAll('.personnel-dialog input,.personnel-dialog select,.personnel-dialog textarea')].filter(x=>!x.checkValidity()).map(x=>({name:x.name,value:x.value,disabled:x.disabled,required:x.required})),submit:document.querySelector('.personnel-dialog button[type=submit]')?.textContent}))()`)))};
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:'http://127.0.0.1:8001/'});
  await wait('typeof renderEmployees === "function" && typeof mountEmployeeTransfers === "function"');
  const click=async selector=>{
   const box=await ev(`(()=>{const b=document.querySelector(${JSON.stringify(selector)});b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,disabled:b.disabled}})()`);assert.equal(box.disabled,false);
   await call('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',clickCount:1});await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x,y:box.y,button:'left',clickCount:1});
  };
  const open=async()=>{await click('[data-personnel-transfer]');await wait('document.querySelector(".personnel-dialog [name=position_id]").options.length>1 && !document.querySelector(".personnel-dialog button[type=submit]").disabled')};
  const save=async()=>{await click('.personnel-dialog button[type=submit]');await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")')};
  await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length > 0');
  await ev(`(()=>{employeeWorkspace.selected=${cfg.employee};renderEmployees();employeeCardOpen(true)})()`);
  await wait('document.querySelector("[data-personnel-transfer]") !== null');
  const already=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>x.item.audit.length)`);
  if(!already){stage='backdated transfer';await open();
  await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.position_id.value='3';f.elements.effective_on.value=${JSON.stringify(cfg.transfer_day)};f.elements.effective_on.dispatchEvent(new Event('change'));f.elements.reason.value='Проверка локального перевода задним числом';})()`);
  await wait('!document.querySelector(".personnel-dialog button[type=submit]").disabled');
  await save();
  }
  const assigned=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>x.item.acting_audit.length)`);
  if(!assigned){stage='acting';await open();
  await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.operation.value='ASSIGN';f.elements.operation.dispatchEvent(new Event('change'));f.elements.position_id.value='14';f.elements.effective_on.value=${JSON.stringify(cfg.acting_start)};f.elements.ends_on.value=${JSON.stringify(cfg.acting_end)};f.elements.reason.value='Проверка локального И.О.';})()`);await save();
  }
  stage='end with objects';await open();await wait('document.querySelector(".personnel-dialog [name=objects]").options.length>0');
  await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.operation.value='END';f.elements.operation.dispatchEvent(new Event('change'));f.elements.acting_root.selectedIndex=1;f.elements.acting_root.dispatchEvent(new Event('change'));f.elements.ends_on.value=${JSON.stringify(cfg.acting_early_end)};f.elements.ends_on.dispatchEvent(new Event('change'));f.elements.reason.value='Проверка возвращения с плановыми объектами';f.elements.objects.options[0].selected=true;})()`);
  await wait('document.querySelector(".personnel-dialog [name=arrival_movement_ref]").options.length>0 && !document.querySelector(".personnel-dialog button[type=submit]").disabled');await save();
  stage='persisted history';result.history=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>({version:x.item.version,primary:x.item.audit.map(e=>({kind:e.kind,source:e.audit_source,actor:e.actor_user_id})),acting:x.item.acting_audit.map(e=>({kind:e.kind,source:e.audit_source,actor:e.actor_user_id,plan:e.plan_change_id}))}))`);
  assert.equal(result.history.version,3);assert.deepEqual(result.history.primary.map(x=>x.kind),['TRANSFER']);assert.deepEqual(result.history.acting.map(x=>x.kind),['ASSIGN','END']);assert.ok(result.history.acting[1].plan);for(const row of [...result.history.primary,...result.history.acting]){assert.equal(row.source,'LOCAL_APP');assert.equal(row.actor,null)}
  await call('Page.reload');await wait('typeof renderEmployees === "function"');await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');await ev(`(()=>{employeeWorkspace.selected=${cfg.employee};renderEmployees();employeeCardOpen(true)})()`);await wait('document.querySelectorAll("[data-acting-history] p").length===2');
  result.reload_persisted=true;result.js_exceptions=errors;assert.equal(errors.length,0);
  fs.writeFileSync(path.join(out,'live-movements.png'),Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  result.success=true;await call('Browser.close');
 }catch(e){result.stage=stage;result.error=e.message;throw e;}finally{if(ws)ws.close();chrome.kill();fs.writeFileSync(path.join(out,'browser_live_saved.json'),JSON.stringify(result,null,2));}
 console.log(JSON.stringify(result));
})().catch(e=>{console.error(e.message);process.exitCode=1});
