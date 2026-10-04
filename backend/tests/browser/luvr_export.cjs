const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json();
 const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method?.includes('download'))console.log(m.method,m.params);});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
 try {
  const folder='C:/Projects/luvr-export-download-'+Date.now();fs.mkdirSync(folder);
  await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:folder.replaceAll('/','\\'),eventsEnabled:true});
  await call('Page.setDownloadBehavior',{behavior:'allow',downloadPath:folder.replaceAll('/','\\')});
  await call('Runtime.enable');await call('Page.enable');await call('Page.navigate',{url:'http://127.0.0.1:8881/'});
  await wait('typeof initLuvrMonth==="function"');
  await ev('document.getElementById("luvrNavButton").click()');
  await wait('!document.getElementById("luvrMonthRefresh").disabled');
  if(await ev('document.getElementById("luvrMonthForm").hidden')){
   await ev('document.getElementById("luvrMonthYear").value=2030;document.getElementById("luvrMonthNumber").dispatchEvent(new Event("change"))');
   await wait('!document.getElementById("luvrMonthRefresh").disabled');
  }
  assert.equal(await ev('document.getElementById("luvrMonthExport").disabled'),true);
  assert.equal(await ev('document.getElementById("luvrMonthExport").title'),'Сначала сформируйте ЛУВР за выбранный месяц');
  await ev('document.getElementById("luvrHeaderSettings").open=true');
  await wait('!document.getElementById("luvrHeaderSave").disabled');
  for(const id of ['luvrDeveloperPosition','luvrDeveloperName','luvrAgreedPosition','luvrAgreedName','luvrLegend']){
    assert.ok(await ev(`document.getElementById('${id}').value.trim().length>0`));
  }
  assert.equal(await ev('document.getElementById("luvrLegend").value.split("\\n").length'),6);
  await ev('document.getElementById("luvrDeveloperName").value="Аниськов В.И.";document.getElementById("luvrAgreedName").value="Тестовый согласующий"');
  await ev('document.getElementById("luvrApproverName").value="Первый И.И.";document.getElementById("luvrHeaderForm").requestSubmit()');
  await wait('!document.getElementById("luvrHeaderSave").disabled');
  await ev('document.getElementById("luvrMonthForm").click()');
  await wait('!document.getElementById("luvrMonthExport").disabled');
  await ev('document.getElementById("luvrApproverName").value="Второй И.И.";document.getElementById("luvrHeaderForm").requestSubmit()');
  await wait('!document.getElementById("luvrHeaderSave").disabled');
  const saved=await ev('(async()=>{const y=document.getElementById("luvrMonthYear").value,m=document.getElementById("luvrMonthNumber").value;return (await(await fetch(`/api/luvr/month/header-snapshot?year=${y}&month=${m}`)).json()).item;})()');
  assert.equal(saved.approver_name_snapshot,'Первый И.И.');
  assert.equal(saved.developer_name_snapshot,'Аниськов В.И.');
  await ev('document.getElementById("luvrDeveloperName").value="Тест Т.Т.";document.getElementById("luvrHeaderForm").requestSubmit()');
  await wait('!document.getElementById("luvrHeaderSave").disabled');
  assert.equal(await ev('document.querySelectorAll("#luvrMonthBody .luvr-specialty-error").length'),2);
  await ev('document.getElementById("luvrMonthExport").click()');
  await wait('!document.getElementById("luvrMonthExport").disabled');
  assert.match(await ev('document.getElementById("luvrMonthError").textContent'),/не указана специальность/);
  assert.equal(fs.readdirSync(folder).filter(f=>f.endsWith('.xlsx')).length,0);
  await ev('(async()=>{const positions=(await(await fetch("/api/positions")).json()).items;for(const p of positions){const r=await fetch("/api/positions/"+p.id,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:p.name,specialty:"ОС"})});if(!r.ok)throw Error(await r.text());}})()');
  await ev('document.getElementById("luvrMonthRefresh").click()');
  await wait('!document.getElementById("luvrMonthRefresh").disabled');
  assert.equal(await ev('document.querySelectorAll("#luvrMonthBody .luvr-specialty-error").length'),0);
  await ev('document.querySelector("#luvrMonthHead [data-sort=full_name]").click()');
  const editId=await ev('Number(document.querySelector("#luvrMonthBody tr").dataset.employee)');
  await ev('document.querySelector("#luvrMonthBody tr [data-action=edit-employee]").click()');
  await wait('!document.getElementById("employeeModal").hidden');
  const current=await ev('(async()=>{return (await(await fetch("/api/employees?include_archived=true")).json()).items;})()');
  const employee=current.find(e=>e.id===editId);
  assert.equal(await ev('document.getElementById("employeeNameInput").value'),employee.full_name);
  await ev('document.getElementById("employeeNameInput").value+=" Проверка";document.getElementById("employeeModalSave").click()');
  await wait('document.getElementById("employeeModal").hidden');
  await wait('!document.getElementById("luvrMonthRefresh").disabled');
  await wait(`document.querySelector('#luvrMonthBody tr[data-employee="${editId}"] .luvr-employee-link').textContent.endsWith('Проверка')`);
  const ordered=await ev('Array.from(document.querySelectorAll("#luvrMonthBody tr"),r=>Number(r.dataset.employee))');
  await ev('document.getElementById("luvrMonthExport").click()');
  let filename;
  for(let i=0;i<200;i++){filename=fs.readdirSync(folder).find(f=>f.endsWith('.xlsx'));if(filename)break;await new Promise(r=>setTimeout(r,50));}
  assert.ok(filename,'Excel download completed: '+await ev('document.getElementById("luvrMonthError").textContent')+JSON.stringify(errors));
  assert.ok(filename.endsWith('.xlsx')&&!filename.includes('_этап'));
  const month=await ev('document.getElementById("luvrMonthNumber").value');
  const year=await ev('document.getElementById("luvrMonthYear").value');
  const data=await(await fetch('http://127.0.0.1:8881/api/luvr/month?year='+year+'&month='+month)).json();
  fs.writeFileSync(folder+'/month.json',JSON.stringify(data.item));
  fs.writeFileSync(folder+'/order.json',JSON.stringify(ordered));
  fs.writeFileSync(folder+'/snapshot.json',JSON.stringify(saved));
  fs.writeFileSync('C:/Projects/luvr-export-download-path.txt',folder+'/'+filename);
  assert.deepEqual(errors,[]);console.log('PASS: unformed disabled, formed enabled, real button downloads '+folder+'/'+filename);
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
