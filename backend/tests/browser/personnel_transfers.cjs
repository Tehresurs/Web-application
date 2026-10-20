// Own restored application server only. Credentials arrive on stdin, never argv.
const fs=require('node:fs'),assert=require('node:assert/strict');let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',v=>input+=v);process.stdin.on('end',async()=>{
 const cfg=JSON.parse(input);let ws,stage='setup';const errors=[];
 try{
 const pages=await(await fetch(`http://127.0.0.1:${cfg.debug_port}/json`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((ok,bad)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',bad,{once:true})});let seq=0;const pending=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params)};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error('Browser evaluation failed: '+String(r.exceptionDetails.exception?.description||r.exceptionDetails.text).replaceAll(cfg.password,'[redacted]'));return r.result.value};
 const wait=async expression=>{for(let i=0;i<160;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50))}throw Error('Timed out waiting for '+expression)};
 const click=async selector=>{
 await new Promise(r=>setTimeout(r,120));
 const box=await ev(`(()=>{const b=document.querySelector(${JSON.stringify(selector)});b.scrollIntoView({block:'center'});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height,disabled:b.disabled,display:getComputedStyle(b).display,visibility:getComputedStyle(b).visibility}})()`);
 assert.equal(box.disabled,false);assert.notEqual(box.display,'none');assert.notEqual(box.visibility,'hidden');assert.ok(box.width>0&&box.height>0);
 await call('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',clickCount:1});await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x,y:box.y,button:'left',clickCount:1});
 };
 const login=async user=>{
 await call('Page.navigate',{url:cfg.url+'/login'});await wait('document.getElementById("authLoginForm")?.dataset.authReady==="true"');
 await ev(`(()=>{const f=document.getElementById('authLoginForm');f.elements.login.value=${JSON.stringify(user)};f.elements.password.value=${JSON.stringify(cfg.password)};})()`);
 await click('#authLoginForm button[type=submit]');
 await wait('typeof renderEmployees==="function" && !document.body.classList.contains("auth-loading")');
 await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');
 await ev(`(()=>{employeeWorkspace.selected=${cfg.employee};renderEmployees();employeeCardOpen(true)})()`);
 };
 await call('Page.enable');await call('Runtime.enable');
 stage='login technician';await login('transfer_tech');await wait('document.querySelector("[data-personnel-transfer]")!==null');
 await click('[data-personnel-transfer]');await wait('document.querySelector(".personnel-dialog [name=position_id]").options.length>1 && !document.querySelector(".personnel-dialog button[type=submit]").disabled');
 await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.position_id.value=${JSON.stringify(String(cfg.position))};f.elements.effective_on.value=${JSON.stringify(cfg.today)};f.elements.reason.value='Browser integration test';})()`);
 await click('.personnel-dialog button[type=submit]');
 assert.equal(await ev('document.querySelector(".personnel-dialog button[type=submit]").textContent'),'Подтвердить перевод');
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
 fs.writeFileSync(cfg.run+'/real-card-transfer-dialog.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
 await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")');
 await wait(`document.querySelector('.employee-identity p.ui-muted')?.textContent===${JSON.stringify(cfg.position_name)}`);
 await wait('document.querySelectorAll(".personnel-history tbody tr").length===2');
 const history=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>({version:x.item.version,audit:x.item.audit.length,current:x.item.current.position_id}))`);
 assert.equal(history.current,cfg.position);assert.equal(history.audit,1);
 await ev('document.getElementById("authLogout").click()');await wait('document.getElementById("authLoginForm")!==null');
 stage='login creator';await login('transfer_creator');await wait('document.querySelector("[data-personnel-review=CORRECT]")!==null');
 stage='correct transfer';await click('[data-personnel-review=CORRECT]');await wait('document.querySelector(".personnel-dialog select").options.length>1');
 await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.position_id.value=${JSON.stringify(String(cfg.correction_position))};f.elements.effective_on.value=${JSON.stringify(cfg.today)};f.elements.reason.value='Creator correction via actual card';})()`);
 await click('.personnel-dialog button[type=submit]');await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")');
 await wait('document.querySelectorAll(".personnel-history details p").length===2');
 stage='cancel transfer';await click('[data-personnel-review=CANCEL]');await ev("document.querySelector('.personnel-dialog [name=reason]').value='Creator cancellation with retained history'");
 await click('.personnel-dialog button[type=submit]');await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")');
 await wait('document.querySelectorAll(".personnel-history details p").length===3');
 const corrected=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>({version:x.item.version,audit:x.item.audit.map(e=>e.kind),current:x.item.current.position_id}))`);
 assert.deepEqual(corrected.audit,['TRANSFER','CORRECT','CANCEL']);assert.equal(corrected.current,cfg.original_position);
 stage='cancel without saving';await click('[data-personnel-transfer]');await wait('document.querySelector(".personnel-dialog [name=position_id]").options.length>1 && !document.querySelector(".personnel-dialog button[type=submit]").disabled');await click('.personnel-dialog button[type=button]');await wait('!document.querySelector(".personnel-dialog")');
 const cancelledVersion=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>x.item.version)`);assert.equal(cancelledVersion,3);
 stage='assign acting';await click('[data-personnel-transfer]');await wait('document.querySelector(".personnel-dialog [name=position_id]").options.length>1 && !document.querySelector(".personnel-dialog button[type=submit]").disabled');
 await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.operation.value='ASSIGN';f.elements.operation.dispatchEvent(new Event('change'));f.elements.position_id.value=String(${cfg.acting_position});f.elements.effective_on.value=${JSON.stringify(cfg.acting_start)};f.elements.ends_on.value=${JSON.stringify(cfg.acting_end)};f.elements.reason.value='Browser acting assignment';})()`);
 await click('.personnel-dialog button[type=submit]');await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")');await wait('document.querySelector("[data-acting-history]")!==null');
 stage='reload acting history';await call('Page.reload');await wait('typeof renderEmployees==="function" && !document.body.classList.contains("auth-loading")');await ev("document.getElementById('employeesNavButton').click()");await wait('document.querySelectorAll("#employeeList tbody tr").length>0');await ev(`(()=>{employeeWorkspace.selected=${cfg.employee};renderEmployees();employeeCardOpen(true)})()`);await wait('document.querySelector("[data-acting-history]")!==null');
 stage='end acting';await click('[data-personnel-transfer]');await wait('document.querySelector(".personnel-dialog [name=objects]").options.length>0');
 await ev(`(()=>{const f=document.querySelector('.personnel-dialog form');f.elements.operation.value='END';f.elements.operation.dispatchEvent(new Event('change'));f.elements.acting_root.selectedIndex=1;f.elements.acting_root.dispatchEvent(new Event('change'));f.elements.ends_on.value=${JSON.stringify(cfg.acting_early_end)};f.elements.ends_on.dispatchEvent(new Event('change'));f.elements.reason.value='Browser return to engineering';f.elements.objects.options[0].selected=true;})()`);
 await wait('document.querySelector(".personnel-dialog [name=arrival_movement_ref]").options.length>0 && !document.querySelector(".personnel-dialog button[type=submit]").disabled');
 await click('.personnel-dialog button[type=submit]');await click('.personnel-dialog button[type=submit]');await wait('!document.querySelector(".personnel-dialog")');await wait('document.querySelectorAll("[data-acting-history] p").length===2');
 const actingHistory=await ev(`fetch('/api/employees/${cfg.employee}/position-transfers').then(r=>r.json()).then(x=>x.item.acting_audit.map(e=>({kind:e.kind,plan:e.plan_change_id})))`);assert.deepEqual(actingHistory.map(e=>e.kind),['ASSIGN','END']);assert.ok(actingHistory[1].plan);
 fs.writeFileSync(cfg.run+'/real-card-movements.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
 await ev('document.getElementById("authLogout").click()');await wait('document.getElementById("authLoginForm")!==null');
 stage='office read only';await login('transfer_office');await wait('document.querySelector(".personnel-history")!==null');assert.equal(await ev('document.querySelector("[data-personnel-transfer]")===null'),true);
 const officeWrite=await ev(`(async()=>{const me=await(await fetch('/api/auth/me')).json();return (await fetch('/api/employees/${cfg.employee}/position-transfers',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token},body:JSON.stringify({position_id:${cfg.position},effective_on:${JSON.stringify(cfg.today)},reason:null,request_id:crypto.randomUUID(),expected_version:1})})).status})()`);assert.equal(officeWrite,403);
 const geometry=[];for(const [width,height] of [[1440,1050],[390,844]]){await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<600});await new Promise(r=>setTimeout(r,100));const row=await ev('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})');geometry.push(row);fs.writeFileSync(cfg.run+`/real-card-history-${width}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'))}
 fs.writeFileSync(cfg.run+'/browser.json',JSON.stringify({success:true,history,corrected,actingHistory,officeWrite,geometry,exceptions:errors.length,scope:'Actual app.main and AuthUI on owned restored DB; business readiness flags supplied by fixture; Creator and DK signature integration not verified'},null,2));
 console.log('Real employee card transfer and Office refusal passed');await call('Browser.close');
 }catch(error){fs.writeFileSync(cfg.run+'/browser_failure.json',JSON.stringify({stage,error:String(error.message).replaceAll(cfg.password,'[redacted]')},null,2));console.error(stage+': '+String(error.message).replaceAll(cfg.password,'[redacted]'));process.exitCode=1}finally{if(ws)ws.close()}
});
