/* Isolated fixture only (:8881); never run a destructive scenario against production. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
let id=0;const pending=new Map(),errors=[],requests=[];
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
const click=id=>ev(`document.getElementById('${id}').click()`);
const api=url=>ev(`fetch(${JSON.stringify(url)}).then(r=>r.json())`);
async function upload(){const root=await call('DOM.getDocument');const input=await call('DOM.querySelector',{nodeId:root.root.nodeId,selector:'#railTicketFiles'});await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.resolve('tests/fixtures/rail/salym_surgut.pdf')]});await wait('document.getElementById("railUploadProgress").hidden && document.querySelector(".rail-ticket-card [data-action=confirm]")!==null');}
try{
await call('Runtime.enable');await call('Network.enable');await call('Page.enable');await call('Page.navigate',{url:'http://127.0.0.1:8881/'});await wait('typeof initRailTickets==="function"');
await click('luvrNavButton');await wait('!document.getElementById("luvrMonthRefresh").disabled');await click('luvrMonthForm');await wait('!document.getElementById("luvrMonthRefresh").disabled');
await click('luvrCalendarNavButton');await wait('document.getElementById("luvrCalendarEmployee").options.length>1');await ev('document.getElementById("luvrCalendarEmployee").value="1";document.getElementById("luvrCalendarEmployee").dispatchEvent(new Event("change"))');await wait('document.querySelectorAll("#luvrCalendarBody tr").length===31');
await click('railTicketsNavButton');await upload();await ev('document.querySelector(".rail-ticket-card [data-action=confirm]").click()');await wait('document.querySelector(".rail-ticket-card").textContent.includes("Сохранённое событие")');
const ticketId=Number(await ev('document.querySelector(".rail-ticket-card").dataset.ticketId'));const ticket=(await api('/api/rail-tickets/'+ticketId)).item,mid=ticket.movement_id;
const before=await api('/api/employees/1/luvr/movements');
await ev('(async()=>{const r=await fetch("/api/employees");const data=await r.json();await openEmployeeModal(data.items.find(e=>e.id===1));document.getElementById("employeeLuvrHistory").open=true;})()');
await wait(`document.querySelector('#employeeLuvrHistoryBody [data-kind="movements"] [data-id="${mid}"]')!==null`);
const row=`document.querySelector('#employeeLuvrHistoryBody [data-kind="movements"] [data-id="${mid}"]')`;
assert.equal(await ev(row+'.querySelectorAll("button").length'),1);assert.equal(await ev(row+'.querySelector("button").textContent'),'Удалить');
await ev(row+'.querySelector("button").click()');await wait('!document.getElementById("railDeleteModal").hidden');assert.match(await ev('document.getElementById("railDeleteModal").textContent'),/связанный с ним ЖД-билет/);
const deleteCount=()=>requests.filter(r=>r.method==='DELETE').length;const count=deleteCount();await click('railDeleteCancel');assert.equal(deleteCount(),count);assert.deepEqual(await api('/api/employees/1/luvr/movements'),before);
await ev(row+'.querySelector("button").click()');await click('railDeleteConfirm');await wait(`${row}===null`);await wait('document.querySelectorAll(".rail-ticket-card").length===0');
assert.equal(await ev(`fetch('/api/rail-tickets/${ticketId}').then(r=>r.status)`),404);
const after=await api('/api/employees/1/luvr/movements');assert.deepEqual(after.items,before.items.filter(m=>m.id!==mid));
assert.ok(requests.some(r=>r.method==='DELETE'&&r.url.endsWith(`/movements/${mid}?delete_ticket=true`)));
assert.ok(requests.filter(r=>r.url.includes('/api/luvr/month?')).length>=3);
assert.ok(requests.filter(r=>r.url.includes('/api/employees/1/luvr/calendar?')).length>=2);
await ev('closeEmployeeModal()');await upload();const newId=Number(await ev('document.querySelector(".rail-ticket-card").dataset.ticketId'));assert.notEqual(newId,ticketId);
await ev('document.querySelector(".rail-ticket-card [data-action=confirm]").click()');await wait('document.querySelector(".rail-ticket-card").textContent.includes("Сохранённое событие")');
const replacement=(await api('/api/rail-tickets/'+newId)).item;assert.notEqual(replacement.movement_id,mid);assert.equal(replacement.movement_type,ticket.movement_type);assert.equal(replacement.movement.event_datetime,ticket.movement.event_datetime);
assert.equal((await api('/api/employees/1/luvr/movements')).items.length,before.items.length);assert.deepEqual(errors,[]);
const report={result:'PASS',deleted:{ticket_id:ticketId,movement_id:mid},replacement:{ticket_id:newId,movement_id:replacement.movement_id},checks:['RAIL delete only, no edit','explicit two-button confirmation','cancel sends no DELETE','history and ticket card removed','other movements preserved','calendar and monthly data refreshed','ordinary parser reupload and confirmation creates one replacement'],errors};fs.writeFileSync('C:/Projects/rail-delete-browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
