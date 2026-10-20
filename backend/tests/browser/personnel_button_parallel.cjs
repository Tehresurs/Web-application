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
  await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');
  const ids=await ev("fetch('/api/employees').then(r=>r.json()).then(x=>x.items.filter(e=>!e.is_archived&&e.position_id).slice(0,3).map(e=>e.id))");
  await ev(`(()=>{const original=window.fetch.bind(window);window.__hrCalls=0;window.fetch=async(input,options)=>{const url=String(input);if(url.includes('/position-transfers')){window.__hrCalls++;await new Promise(r=>setTimeout(r,0));}return original(input,options)}})()`);
  result.cards=[];
  for(const id of ids){
   const initial=await ev(`(()=>{window.__hrStarted=performance.now();employeeWorkspace.selected=${id};employeeWorkspace.item=null;renderEmployees();employeeCardOpen(true);window.__hrButton=document.querySelector('[data-personnel-transfer]');const b=window.__hrButton,r=b?.getBoundingClientRect();return {visible:!!b&&r.width>0&&r.height>0,disabled:b?.disabled,calls:window.__hrCalls,x:r?.x,y:r?.y}})()`);
   assert.equal(initial.visible,true);assert.equal(initial.disabled,true);
   await wait('document.querySelector("[data-personnel-transfer]")?.disabled===false');
   const loaded=await ev(`(()=>{const b=document.querySelector('[data-personnel-transfer]'),r=b.getBoundingClientRect();return {same:b===window.__hrButton,x:r.x,y:r.y,calls:window.__hrCalls}})()`);
   assert.equal(loaded.same,true);assert.equal(loaded.x,initial.x);assert.equal(loaded.y,initial.y);result.cards.push({visible_synchronously:true,same_node:true,stable_position:true,activation_ms:await ev('Math.round(performance.now()-window.__hrStarted)')});
  }
  assert.equal(await ev('window.__hrCalls'),ids.length*2);result.display_requests=ids.length*2;
  await open();await wait('document.querySelector(".personnel-dialog [name=objects]").options.length>0');
  result.operations=[];
  for(const kind of ['TRANSFER','ASSIGN','END']){
   const state=await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.operation.value=${JSON.stringify(kind)};f.elements.operation.dispatchEvent(new Event('change'));return {operation:f.elements.operation.value,position:!f.elements.position_id.disabled,objects:!f.elements.objects.disabled}})()`);
   assert.equal(state.operation,kind);assert.equal(state.position,kind!=='END');assert.equal(state.objects,kind==='END');result.operations.push(kind);
  }
  await click('.personnel-dialog button[type=button]');await wait('!document.querySelector(".personnel-dialog")');
  result.saved_data=false;result.js_exceptions=errors;assert.equal(errors.length,0);
  result.success=true;await call('Browser.close');
 }catch(e){result.stage=stage;result.error=e.message;throw e;}finally{if(ws)ws.close();chrome.kill();fs.writeFileSync(path.join(out,'browser_button_parallel.json'),JSON.stringify(result,null,2));}
 console.log(JSON.stringify(result));
})().catch(e=>{console.error(e.message);process.exitCode=1});
