// Live smoke: no login, no account creation, only anonymous rejected HR writes.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
(async()=>{
 const out=path.resolve('backend/output/security/personnel_working_install_20261020T122602Z');
 const server=require('node:net').createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;await new Promise(r=>server.close(r));
 const chrome=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+port,'--user-data-dir='+path.join(out,'readonly-browser-profile'),'about:blank'],{windowsHide:true,stdio:'ignore'});
 let ws;const result={success:false,accounts_created:false};
 try{
  let pages;for(let i=0;i<100;i++){try{pages=await(await fetch('http://127.0.0.1:'+port+'/json')).json();break}catch{}await new Promise(r=>setTimeout(r,100));}
  ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
  let seq=0;const pending=new Map(),errors=[];ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
  const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value};
  const wait=async expression=>{for(let i=0;i<160;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Browser readiness timeout')};
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:'http://127.0.0.1:8001/'});
  await wait('typeof renderEmployees === "function" && typeof mountEmployeeTransfers === "function"');
  await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length > 0');
  await ev('(async()=>{const d=await fetch("/api/employees").then(r=>r.json());employeeWorkspace.selected=d.items[0].id;renderEmployees();employeeCardOpen(true)})()');
  await wait('document.querySelector("[data-personnel-session-required]") !== null');
  result.disabled_button=await ev('document.querySelector("[data-personnel-session-required]").disabled');assert.equal(result.disabled_button,true);
  result.operations=await ev(`(async()=>{const employees=await fetch('/api/employees').then(r=>r.json()),positions=await fetch('/api/positions').then(r=>r.json());const eid=employees.items[0].id,pid=positions.items[0].id;const base='/api/employees/'+eid+'/position-transfers';const rid=crypto.randomUUID();const common={request_id:rid,expected_version:0};const cases=[['transfer',base,{...common,position_id:pid,effective_on:'2030-01-01'}],['acting',base+'/acting',{...common,position_id:pid,starts_on:'2030-01-01',ends_on:'2030-01-03'}],['end',base+'/acting/'+rid+'/end',{...common,ends_on:'2030-01-02',reason:'Anonymous boundary check',plan:{effective_from:'2030-01-03',period_kind:'EXPLICIT',period_start:'2030-01-03',period_end:'2030-01-31',assignment_state:'OBJECTS',items:[{object_id:1}]}}]];const results={};for(const [name,url,payload] of cases){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});results[name]=r.status;}return results})()`);
  assert.deepEqual(result.operations,{transfer:403,acting:403,end:403});result.js_exceptions=errors;assert.equal(errors.length,0);
  result.success=true;await call('Browser.close');
 }finally{if(ws)ws.close();chrome.kill();fs.writeFileSync(path.join(out,'browser_readonly.json'),JSON.stringify(result,null,2));}
 console.log(JSON.stringify(result));
})().catch(e=>{console.error(e.message);process.exitCode=1});
