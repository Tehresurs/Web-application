const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=process.env.EMPLOYEE_TEST_URL||'http://127.0.0.1:8881';
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+expression);};
 const click=key=>ev(`document.getElementById('${key}').click()`);
 const change=(key,value)=>ev(`document.getElementById('${key}').value=${JSON.stringify(value)};document.getElementById('${key}').dispatchEvent(new Event('change'))`);
 try{
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:base+'/'});await wait('typeof renderEmployeeWorkspace==="function" && typeof openEmployeeModal==="function"');
  await click('employeesNavButton');await wait('document.querySelectorAll("#employeeList tbody tr").length>0');
  assert.equal(await ev('document.querySelectorAll("#employeeProfile [role=tab]").length'),5);
  for(const [width,height] of [[1920,1080],[1366,768],[900,768],[390,844]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'),'no page overflow '+width);
  }
  await call('Emulation.setDeviceMetricsOverride',{width:1600,height:900,deviceScaleFactor:1,mobile:false});
  await click('employeeProfileTab-equipment');assert.ok(await ev('document.getElementById("employeeProfilePanel").textContent.includes("Раздел будет добавлен позже")'));
  await click('employeeProfileTab-training');assert.ok(await ev('document.getElementById("employeeProfilePanel").textContent.includes("Раздел будет добавлен позже")'));
  await click('employeeProfileTab-history');await wait('!document.getElementById("employeeProfilePanel").textContent.includes("Загрузка")');
  assert.equal(await ev('document.querySelectorAll("#employeeProfilePanel .ui-error").length'),0);
  await click('employeeProfileTab-assignments');await wait('!document.getElementById("employeeProfilePanel").textContent.includes("Загрузка")');
  assert.equal(await ev('document.querySelectorAll("#employeeProfilePanel .ui-error").length'),0);
  await click('employeeProfileTab-main');await wait('!document.getElementById("employeeProfilePanel").textContent.includes("Загрузка")');
  if(!process.env.EMPLOYEE_TEST_URL){
   await click('addEmployeeButton');await wait('!document.getElementById("employeeModal").hidden');
   await ev(`document.getElementById('employeeNameInput').value='Карточка Тестовая';document.getElementById('employeePhoneInput').value='777-UI';document.getElementById('employeeEmailInput').value='card@example.com';document.getElementById('employeeNrsNumber').value='НРС-UI-777'`);
   await click('employeeModalSave');await wait('document.getElementById("employeeModal").hidden');await wait('document.querySelector(".employee-identity h2")?.textContent==="Карточка Тестовая"');
   const employeeId=await ev('employeeWorkspace.selected');
   assert.equal(await ev('employeeWorkspace.item.email'),'card@example.com');
   await ev(`(async()=>{const crew=await employeeAbsenceRequest('/api/crews','POST',{driver_full_name:'Водитель карточки',driver_phone:'555-CARD',vehicle_make:'Test car',vehicle_plate:'TEST-01'});const e=employeeWorkspace.item;await employeeAbsenceRequest('/api/employees/'+e.id,'PATCH',{full_name:e.full_name,phone:e.phone,position_id:e.position_id,crew_id:crew.id});await loadEmployees();})()`);
   await wait(`Array.from(document.querySelectorAll('#employeeProfile button')).some(b=>b.textContent==='Перейти к экипажу')`);
   await ev(`Array.from(document.querySelectorAll('#employeeProfile button')).find(b=>b.textContent==='Перейти к экипажу').click()`);
   await wait('!document.getElementById("crewModal").hidden');
   assert.equal(await ev('document.getElementById("crewDriverInput").value'),'Водитель карточки');
   await click('crewModalCancel');await click('employeesNavButton');
   await wait('document.querySelector(".employee-identity h2")?.textContent==="Карточка Тестовая"');
   await ev(`document.getElementById('employeeSearchInput').value='НРС-UI-777';document.getElementById('employeeSearchInput').dispatchEvent(new Event('input'))`);
   assert.equal(await ev('document.querySelectorAll("#employeeList tbody tr").length'),1);
   await ev('document.querySelector("#employeeProfile .ui-button-primary").click()');await wait('document.querySelector(".employee-inline-editor")!=null');
   assert.equal(await ev('document.getElementById("employeeModal").hidden'),true);
   assert.equal(await ev('document.querySelector(".employee-inline-editor [name=specialty]").readOnly'),true);
   await ev(`document.querySelector('.employee-inline-editor [name=full_name]').value='UNSAVED';document.querySelector('.employee-inline-editor button[type=button]').click()`);
   await wait('document.querySelector(".employee-inline-editor")==null');
   assert.notEqual(await ev('employeeWorkspace.item.full_name'),'UNSAVED');
   await ev('document.querySelector("#employeeProfile .ui-button-primary").click()');await wait('document.querySelector(".employee-inline-editor")!=null');
   await ev(`document.querySelector('.employee-inline-editor [name=full_name]').value='\u041a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u0418\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u0430\u044f';document.querySelector('.employee-inline-editor [name=dismissal_date]').value='2026-01-01';document.querySelector('.employee-inline-editor').requestSubmit()`);
   await wait('document.querySelector(".employee-inline-editor")==null');
   assert.equal(await ev('employeeWorkspace.item.dismissal_date'),'2026-01-01');
   await change('employeeStatusFilter','Уволен');assert.equal(await ev('document.querySelectorAll("#employeeList tbody tr").length'),1);
   await change('employeeStatusFilter','Работает');assert.equal(await ev('document.querySelectorAll("#employeeList tbody tr").length'),0);
   await change('employeeStatusFilter','');
   await ev('window.confirm=()=>true;document.querySelectorAll("#employeeProfile .employee-profile-actions button")[1].click()');await wait('document.querySelectorAll("#employeeList tbody tr").length===0');
   await change('employeeArchiveFilter','archived');await wait('document.querySelectorAll("#employeeList tbody tr").length===1');
   assert.equal(await ev('employeeWorkspace.selected'),employeeId);
   await ev('document.querySelectorAll("#employeeProfile .employee-profile-actions button")[1].click()');await wait('document.querySelectorAll("#employeeList tbody tr").length===0');
   await change('employeeArchiveFilter','active');await wait('document.querySelectorAll("#employeeList tbody tr").length===1');
   await ev(`document.getElementById('employeeSearchInput').value='';document.getElementById('employeeSearchInput').dispatchEvent(new Event('input'))`);
  }
  const name=await ev('document.querySelector(".employee-identity h2").textContent');
  await change('employeePlaceFilter','OBJECT');assert.ok(await ev('Array.from(document.querySelectorAll("#employeeList tbody tr")).every(r=>r.children[3].textContent==="Объект")'));
  await change('employeePlaceFilter','');await change('employeeScheduleFilter','SHIFT');assert.ok(await ev('Array.from(document.querySelectorAll("#employeeList tbody tr")).every(r=>r.children[4].textContent==="Вахта")'));
  await change('employeeScheduleFilter','');
  await ev('document.querySelectorAll("#employeeList tbody tr")[1]?.click()');assert.ok(await ev('document.querySelector("#employeeList tr[aria-selected=true]")!=null'));
  await wait('!document.getElementById("employeeProfilePanel").textContent.includes("Загрузка")');
  if(process.env.EMPLOYEE_TEST_URL){
   const result=await ev(`(async()=>{const today=employeeToday(),[year,month]=today.split('-');return (await (await fetch('/api/luvr/month?year='+year+'&month='+Number(month)+'&as_of_date='+today)).json()).item;})()`);
   const calculated=result.employees.find(e=>e.duration.current_shift_days!=null||e.duration.current_off_shift_days!=null);
   if(calculated){
    await change('employeeArchiveFilter','all');await wait(`document.querySelector('#employeeList tr[data-employee="${calculated.employee_id}"]')!=null`);
    await ev(`document.querySelector('#employeeList tr[data-employee="${calculated.employee_id}"]').click()`);await wait('!document.getElementById("employeeProfilePanel").textContent.includes("Загрузка")');
    const values=await ev(`Object.fromEntries(Array.from(document.querySelectorAll('#employeeProfilePanel dt'),dt=>[dt.textContent,dt.nextElementSibling.textContent]))`);
    await wait('document.querySelector("[data-duration-value=shift]").textContent!=="…"');
    const display=require('../../app/static/js/employee_visuals.js').employeeDurationValues(calculated.duration);
    assert.equal(await ev('document.querySelector("[data-duration-value=shift]").textContent'),String(display.shift));
    assert.equal(await ev('document.querySelector("[data-duration-value=off]").textContent'),String(display.off));
   }
  }
  fs.writeFileSync('C:/Projects/employee-workspace.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  assert.deepEqual(errors,[]);console.log('PASS: employee list, filters, selection, tabs, responsive layout, '+(process.env.EMPLOYEE_TEST_URL?'read-only':'create/edit/dismissal/archive/restore')+', no JS exceptions');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
