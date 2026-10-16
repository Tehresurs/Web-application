// Mutations are restricted to the isolated browser fixture server.
const assert=require('node:assert/strict');
(async()=>{
 const url='http://127.0.0.1:8881',cdp='http://127.0.0.1:9234';
 const request=async(path,method='GET',body)=>{const r=await fetch(url+path,{method,headers:{'Content-Type':'application/json'},body:body&&JSON.stringify(body)});const data=await r.json();assert.equal(r.status,200,JSON.stringify(data));return data;};
 const suffix=Date.now(),names=['Member A '+suffix,'Member B '+suffix];
 for(const name of names)await request('/api/crews','POST',{driver_full_name:name,driver_phone:'123',vehicle_make:'Car',vehicle_plate:name});
 // Existing API returns an ID for creation; read back canonical directory values.
 const all=(await request('/api/crews')).items, a=all.find(c=>c.driver_full_name===names[0]),b=all.find(c=>c.driver_full_name===names[1]);
 const ids=[];for(const name of ['Crew Test One','Crew Test Two'])ids.push((await request('/api/employees','POST',{full_name:name+' '+suffix,phone:'987'})).id);
 const before=(await request('/api/employees')).items.filter(e=>ids.includes(e.id));
 const page=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json(),ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0,accept=false,dialogs=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Page.javascriptDialogOpening'){dialogs++;call('Page.handleJavaScriptDialog',{accept});}};
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expr=>{for(let i=0;i<150;i++){if(await ev(expr))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expr);};
 const pick=async crew=>{await ev(`document.querySelector('#crewList [data-record-id="${crew}"]').click()`);await wait(`document.querySelector('.crew-members h3')`);};
 const select=async employees=>{await ev(`Array.from(document.querySelectorAll('.crew-members button')).find(b=>b.textContent==='Добавить сотрудников').click()`);for(const employee of employees)await ev(`document.querySelector('.crew-candidates [data-employee-id="${employee}"]').click()`);};
 const apply=()=>ev(`Array.from(document.querySelectorAll('.crew-members button')).find(b=>b.textContent.startsWith('Закрепить выбранных')).click()`);
 try{
  await call('Page.enable');await call('Runtime.enable');await call('Page.navigate',{url});await wait(`typeof renderCrewMembers==='function'`);
  await ev(`document.getElementById('crewsNavButton').click()`);await wait(`document.querySelector('#crewList .directory-choice')`);await pick(a.id);
  await select(ids);await apply();await wait(`document.querySelectorAll('.crew-member').length===2`);
  assert.equal((await request('/api/employees')).items.filter(e=>ids.includes(e.id)&&e.crew_id===a.id).length,2);
  await pick(b.id);await select([ids[0]]);await apply();assert.equal(dialogs,1);assert.equal((await request('/api/employees')).items.find(e=>e.id===ids[0]).crew_id,a.id);
  accept=true;await apply();await wait(`document.querySelectorAll('.crew-member').length===1`);
  await wait(`employeeItems.some(e=>e.id===${ids[0]}&&e.crew_id===${b.id})`);
  await select([ids[1]]);
  await request('/api/crew-memberships','PATCH',{target_crew_id:null,employees:[{employee_id:ids[1],expected_crew_id:a.id}]});
  await apply();await wait(`document.querySelector('.crew-members .ui-error').textContent.includes('изменилось')`);
  assert.equal(await ev(`document.querySelectorAll('.crew-candidates input:checked').length`),0);
  await select([ids[1]]);await apply();await wait(`document.querySelectorAll('.crew-member').length===2`);
  await ev(`document.querySelector('.crew-member button').click()`);await wait(`document.querySelectorAll('.crew-member').length===1`);
  await call('Page.reload');await wait(`typeof renderCrewMembers==='function'`);await ev(`document.getElementById('crewsNavButton').click()`);await wait(`document.querySelector('#crewList .directory-choice')`);await pick(b.id);assert.equal(await ev(`document.querySelectorAll('.crew-member').length`),1);
  await select([ids[0]]);await ev(`document.querySelector('.crew-member-picker input[type=search]').value='zzzz';document.querySelector('.crew-member-picker input[type=search]').dispatchEvent(new Event('input'))`);assert.equal(await ev(`document.querySelectorAll('.crew-candidate').length`),0);
  await ev(`Array.from(document.querySelectorAll('.crew-member-picker button')).find(b=>b.textContent==='Отмена').click()`);
  const after=(await request('/api/employees')).items.filter(e=>ids.includes(e.id));
  for(let i=0;i<before.length;i++){const strip=e=>Object.fromEntries(Object.entries(e).filter(([k])=>!k.startsWith('crew')&&!['driver_full_name','driver_phone','vehicle_make','vehicle_plate'].includes(k)));assert.deepEqual(strip(after[i]),strip(before[i]));}
  const remaining=after.find(e=>e.crew_id===b.id);
  await ev(`document.getElementById('employeesNavButton').click()`);
  await wait(`document.querySelector('#employeeList [data-employee="${remaining.id}"] button')`);
  await ev(`document.querySelector('#employeeList [data-employee="${remaining.id}"] button').click();document.getElementById('employeeProfileTab-assignments').click()`);
  await wait(`document.getElementById('employeeProfilePanel').textContent.includes(${JSON.stringify(names[1])})`);
  assert.deepEqual(errors,[]);console.log('Crew browser: batch, transfer/cancel, conflict, refresh, removal, reload, search, preserved fields OK');
 }finally{ws.close();await fetch(cdp+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
