/* Default: isolated fixture at :8881. LUVR_READONLY_URL checks real rows without mutations. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {sortLuvrEmployees}=require('../../app/static/js/luvr_sort.js');
const {luvrDurationSummary}=require('../../app/static/js/luvr_duration.js');
(async()=>{
const base=process.env.LUVR_READONLY_URL||'http://127.0.0.1:8881';
const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
let id=0;const pending=new Map(),errors=[],requests=[];
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
const click=id=>ev(`document.getElementById('${id}').click()`),ready=()=>wait('!document.getElementById("luvrMonthRefresh").disabled');
const api=url=>ev(`fetch(${JSON.stringify(url)}).then(r=>r.json())`);
async function upload(name){
 const root=await call('DOM.getDocument');const input=await call('DOM.querySelector',{nodeId:root.root.nodeId,selector:'#railTicketFiles'});
 await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.resolve('tests/fixtures/rail/'+name)]});
 await wait('document.querySelectorAll(".rail-ticket-card").length>0 && document.getElementById("railUploadProgress").hidden');
}
async function verify(expected){
 const rows=await ev(`Array.from(document.querySelectorAll('#luvrMonthBody tr')).map(r=>({id:Number(r.dataset.employee),number:r.cells[0].textContent,name:r.cells[1].textContent,days:Array.from(r.querySelectorAll('[data-date]')).map(b=>[b.dataset.date,b.textContent]),totals:Array.from(r.querySelectorAll('[data-total]')).map(c=>[c.dataset.total,c.textContent]),status:r.querySelector('[data-action="duration-detail"]')?.textContent||''}))`);
 assert.deepEqual(rows.map(r=>r.id),expected.map(e=>e.employee_id));
 rows.forEach((r,i)=>{const e=expected[i];assert.equal(r.number,String(i+1));assert.equal(r.name,e.full_name+(e.is_archived?' (архив)':''));assert.deepEqual(r.days,e.days.map(d=>[d.date,d.final_display]));for(const [k,v] of r.totals)assert.equal(v,String(e.totals[k]).replace('.',','));assert.equal(r.status,luvrDurationSummary(e.duration));});
}
try{
await call('Runtime.enable');await call('Network.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false});await call('Page.navigate',{url:base+'/'});await wait('typeof sortLuvrEmployees==="function"');const origin=await ev('performance.timeOrigin');
assert.equal(await ev('document.querySelectorAll(".sidebar #luvrNavButton").length'),1);assert.equal(await ev('document.querySelectorAll(".sidebar #railTicketsNavButton,.sidebar #luvrMonthNavButton,.sidebar #luvrCalendarNavButton").length'),0);
await click('luvrNavButton');await click('luvrMonthNavButton');await ready();assert.equal(await ev('document.getElementById("luvrMonthNavButton").getAttribute("aria-current")'),'page');
await click('railTicketsNavButton');assert.equal(await ev('document.getElementById("railTicketsPage").hidden'),false);
if(!process.env.LUVR_READONLY_URL){
 await upload('salym_surgut.pdf');
 if(await ev('!!document.querySelector(".rail-ticket-card [data-action=confirm]")')){
  await ev('document.querySelector(".rail-ticket-card [data-action=confirm]").click()');await wait('document.querySelector(".rail-ticket-card").textContent.includes("Сохранённое событие")');
 }
 await upload('salym_surgut.pdf');await wait('document.querySelector(".rail-ticket-card").textContent.includes("Билет уже обработан")');
 await upload('round_trip.pdf');await wait('Array.from(document.querySelectorAll(".rail-ticket-card")).filter(c=>c.textContent.includes("round_trip.pdf")).length===2');
}
await click('luvrMonthNavButton');await ready();
const data=(await api('/api/luvr/month?year=2026&month=10')).item;assert.ok(data.employees.length>=60);await verify(sortLuvrEmployees(data.employees));
if(!process.env.LUVR_READONLY_URL)fs.writeFileSync('C:/Projects/luvr-tabs-browser.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
const requestCount=requests.length;
for(const field of ['full_name','position_name','specialty','work_location','work_schedule','current_state','work_days_total','travel_days_total','off_shift_days_total','downtime_days_total']){
 for(let n=0;n<2;n++){
  await ev(`document.querySelector('[data-sort="${field}"]').click()`);
  const aria=await ev(`document.querySelector('[data-sort="${field}"]').parentElement.getAttribute('aria-sort')`);
  await verify(sortLuvrEmployees(data.employees,field,aria==='ascending'?'asc':'desc'));
 }
}
assert.equal(requests.length,requestCount,'Sorting must send no API requests');
await ev('document.querySelector(".luvr-month-scroll").scrollLeft=100000');const left=await ev('document.querySelector(".luvr-month-scroll").scrollLeft');
await ev('document.querySelector("[data-sort=off_shift_days_total]").click()');assert.equal(await ev('document.querySelector(".luvr-month-scroll").scrollLeft'),left);
await verify(sortLuvrEmployees(data.employees,'off_shift_days_total','asc'));
const order=await ev('Array.from(document.querySelectorAll("#luvrMonthBody tr")).map(r=>r.dataset.employee)');
await click('luvrCalendarNavButton');await wait('document.getElementById("luvrCalendarEmployee").options.length>1');
await ev(`document.getElementById('luvrCalendarEmployee').value='${data.employees[0].employee_id}';document.getElementById('luvrCalendarMonth').value='2026-10';document.getElementById('luvrCalendarEmployee').dispatchEvent(new Event('change'))`);await wait('document.querySelectorAll("#luvrCalendarBody tr").length===31');
await click('luvrMonthNavButton');await ready();assert.deepEqual(await ev('Array.from(document.querySelectorAll("#luvrMonthBody tr")).map(r=>r.dataset.employee)'),order);
await ev('document.querySelector(".luvr-month-scroll").scrollLeft=0;document.querySelector("#luvrMonthBody tr [data-date]").click()');
const first=sortLuvrEmployees(data.employees,'off_shift_days_total','asc')[0];assert.ok((await ev('document.getElementById("luvrMonthDetail").textContent')).includes(first.full_name));
if(!process.env.LUVR_READONLY_URL){
 await ev('document.getElementById("luvrMonthValue").value="DOWNTIME";document.getElementById("luvrMonthEditor").requestSubmit()');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();
 const changed=(await api('/api/luvr/month?year=2026&month=10')).item.employees;
 assert.equal(changed.find(e=>e.employee_id===first.employee_id).days[0].final_code,'DOWNTIME');
 for(const employee of data.employees)if(employee.employee_id!==first.employee_id)assert.deepEqual(changed.find(e=>e.employee_id===employee.employee_id),employee);
 await ev(`document.querySelector('#luvrMonthBody tr[data-employee="${first.employee_id}"] [data-date]').click()`);await click('luvrMonthRestore');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();
 const restored=(await api('/api/luvr/month?year=2026&month=10')).item.employees.find(e=>e.employee_id===first.employee_id);assert.deepEqual(restored,first);
}else await click('luvrMonthCancel');
assert.equal(await ev('performance.timeOrigin'),origin);assert.deepEqual(errors,[]);
const report={result:'PASS',mode:process.env.LUVR_READONLY_URL?'real employees, read-only':'isolated fixture',employees:data.employees.length,checks:['single sidebar module','three existing tabs without reload','rail upload/confirmation/duplicates/multipage in isolated mode','10 sort fields both directions','every employee ID/name/day/total/status remains attached','sort sends no requests','scroll retained','sort retained across detailed calendar','day detail targets sorted employee'],errors};
fs.writeFileSync('C:/Projects/luvr-ui-'+(process.env.LUVR_READONLY_URL?'real':'isolated')+'-browser.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
