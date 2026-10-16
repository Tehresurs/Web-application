const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json();const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+expression);};
 const ready=()=>wait('document.querySelector("[data-duration-value=shift]")?.textContent!=="…" && document.getElementById("employeeStateBadge")?.textContent!=="Загрузка…"');
 try{
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:(process.env.EMPLOYEE_TEST_URL||'http://127.0.0.1:8000')+'/'});await wait('typeof employeeQuickActions==="function"&&typeof renderEmployees==="function"');
  await ev('document.getElementById("employeesNavButton").click()');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');await ready();
  const selected=await ev(`(async()=>{const [year,month]=employeeToday().split('-');const data=(await(await fetch('/api/luvr/month?year='+year+'&month='+Number(month))).json()).item;const e=data.employees.find(e=>e.duration.current_shift_days!=null&&!e.is_archived);if(e){employeeWorkspace.selected=e.employee_id;renderEmployees();}return employeeWorkspace.selected;})()`);await ready();
  await ev('employeeCardOpen(true)');
  await ev('document.querySelector("#employeeProfile .ui-button-primary").click()');
  await wait('document.querySelector(".employee-inline-editor")!=null');
  assert.equal(await ev('document.getElementById("employeeModal").hidden'),true);
  await ev(`(()=>{const f=document.querySelector('.employee-inline-editor');f.elements.work_location.value='OFFICE';f.elements.work_location.onchange();})()`);
  assert.equal(await ev(`(()=>{const f=document.querySelector('.employee-inline-editor');return Array.from(f.elements.position_id.options).filter(o=>o.value).every(o=>positionItems.find(p=>String(p.id)===o.value)?.work_location==='OFFICE');})()`),true);
  assert.equal(await ev('document.querySelector(".employee-inline-editor [name=specialty]").readOnly'),true);
  await ev('document.querySelector(".employee-inline-editor button[type=button]").click()');await ready();
  for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await ev('window.scrollTo(0,0)');
   await new Promise(r=>setTimeout(r,100));
   const geometry=await ev(`(()=>{const q=document.querySelector('.employee-quick-actions').getBoundingClientRect(),a=document.querySelector('.employee-workspace').getBoundingClientRect(),b=document.querySelector('#employeeProfile').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth+1,quickBottom:q.bottom,cardLeft:b.left,listLeft:a.left,badges:document.querySelectorAll('.employee-header-badges>.ui-badge').length};})()`);
   assert.equal(geometry.overflow,false);assert.equal(geometry.badges,2);assert.ok(Math.abs(geometry.cardLeft-geometry.listLeft)<2);
   if(width===1920)assert.ok(geometry.quickBottom<=height,'Quick actions visible at 1920: '+JSON.stringify(geometry));
   fs.mkdirSync('C:/Projects/employee-card-review',{recursive:true});fs.writeFileSync(`C:/Projects/employee-card-review/employee-card-${width}x${height}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  }
  for(const [key,kind] of [['truck','movements'],['alert','duration-exceptions']]){
   await ev(`document.querySelector('[data-quick-action="${key}"]').click()`);await wait(`document.querySelector('#employeeLuvrHistory [data-kind="${kind}"] .luvr-history-editor')!=null`);
   assert.equal(await ev('employeeLuvrController.employeeId'),selected);await ev('document.getElementById("employeeModalCancel").click()');await ready();
  }
  await ev('document.querySelector("[data-quick-action=plus]").click()');await wait('document.querySelector("[data-absence-form=other]")!=null');assert.equal(await ev('employeeWorkspace.selected'),selected);
  await ev('document.getElementById("employeeProfileTab-main").click()');await ready();
  await ev('document.querySelector("[data-quick-action=calendar]").click()');await wait(`document.getElementById('luvrCalendarEmployee').value==='${selected}'&&document.querySelectorAll('#luvrCalendarBody tr').length===31`);
  await ev('document.getElementById("employeesNavButton").click()');await ready();
  await call('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});await ev('window.scrollTo(0,0)');
  assert.deepEqual(errors,[]);console.log('PASS: employee card 1920/1600/1366, four existing quick actions, no writes or JS errors');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
