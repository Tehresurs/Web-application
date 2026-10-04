/* Run against the isolated browser fixture only: node tests/browser_luvr_scroll.cjs */
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
const pages=await(await fetch('http://127.0.0.1:9234/json')).json(),ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
let id=0;const pending=new Map(),errors=[];
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const wait=async exp=>{for(let i=0;i<200;i++){if(await ev(exp))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+exp);};
const settle=()=>ev('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
const click=id=>ev(`document.getElementById('${id}').click()`),ready=()=>wait('!document.getElementById("luvrMonthRefresh").disabled');
const bar='document.querySelector(".luvr-fixed-scroll")',box='document.querySelector(".luvr-month-scroll")';
const sync=()=>wait(`Math.abs(${bar}.scrollLeft-${box}.scrollLeft)<1`);
async function dragEnd(){
 await ev(`${bar}.scrollLeft=0`);await sync();await settle();
 const b=await ev(`(()=>{const b=${bar},r=b.getBoundingClientRect();return {left:r.left,right:r.right,y:r.bottom-8,thumb:b.clientWidth*b.clientWidth/b.scrollWidth};})()`);
 await call('Input.dispatchMouseEvent',{type:'mousePressed',x:b.left+b.thumb/2,y:b.y,button:'left',clickCount:1});
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:b.right-4,y:b.y,button:'left',buttons:1});
 await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:b.right-4,y:b.y,button:'left',clickCount:1});
 await wait(`${box}.scrollLeft>${box}.scrollWidth-${box}.clientWidth-3`);await sync();
}
async function sticky(){
 const p=await ev(`(()=>{const c=${box}.getBoundingClientRect(),r=document.querySelector('#luvrMonthBody tr'),n=r.cells[0].getBoundingClientRect(),f=r.cells[1].getBoundingClientRect(),h=document.querySelector('#luvrMonthHead').cells[0].getBoundingClientRect();return {top:c.top,left:c.left,n:n.left,f:f.left,nright:n.right,header:h.top};})()`);
 assert.ok(Math.abs(p.left-p.n)<1,JSON.stringify(p));assert.ok(Math.abs(p.f-p.nright)<1,JSON.stringify(p));assert.ok(Math.abs(p.header-Math.max(0,p.top))<2,JSON.stringify(p));
}
try{
await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false});
await call('Page.navigate',{url:'http://127.0.0.1:8881/'});await wait('typeof initLuvrScroll==="function"');await click('luvrMonthNavButton');await ready();await click('luvrMonthForm');await ready();
assert.ok(await ev('document.querySelectorAll("#luvrMonthBody tr").length>=70'));
await ev(`window.scrollTo(0,${box}.getBoundingClientRect().top+scrollY+2)`);await wait(`!${bar}.hidden`);await settle();
const beforeY=await ev('scrollY');await dragEnd();assert.equal(await ev('scrollY'),beforeY);await sticky();
// Native wheel still scrolls vertically; header and identifiers remain visible.
await call('Input.dispatchMouseEvent',{type:'mouseWheel',x:1100,y:350,deltaX:0,deltaY:850});await wait(`scrollY>${beforeY}+100`);await settle();await sticky();assert.equal(await ev(bar+'.hidden'),false);
await ev(`${bar}.scrollLeft=0`);await sync();assert.equal(await ev(box+'.scrollLeft'),0);
await ev(`${box}.scrollLeft=350`);await sync();assert.ok(await ev(bar+'.scrollLeft>0'));
await ev(`window.scrollTo(0,${box}.getBoundingClientRect().bottom+scrollY-innerHeight+8)`);await wait(`${bar}.hidden`);
await ev(`window.scrollTo(0,${box}.getBoundingClientRect().top+scrollY+2)`);await wait(`!${bar}.hidden`);
for(const [width,height] of [[1600,900],[1920,1080],[1100,700]]){
 await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await settle();await sync();
 assert.ok(await ev(`Math.abs(${bar}.clientWidth-${box}.clientWidth)<1`));await dragEnd();await sticky();
}
await call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false});await settle();await dragEnd();
fs.writeFileSync('C:/Projects/luvr-scroll-browser.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
// Actual click on day 31 after horizontal scrolling must hit the original day button.
await ev(`document.querySelector('#luvrMonthBody tr[data-employee="1"]').scrollIntoView({block:"center",inline:"nearest"})`);await settle();
const point=await ev(`(()=>{const r=document.querySelector('#luvrMonthBody tr[data-employee="1"] [data-date="2026-10-31"]').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`);
await call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});await call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
await wait('!document.getElementById("luvrMonthEditor").hidden');
assert.match(await ev('document.getElementById("luvrMonthDetail").textContent'),/2026-10-31/);
await ev('document.getElementById("luvrMonthValue").value="DOWNTIME";document.getElementById("luvrMonthEditor").requestSubmit()');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();
assert.equal(await ev(`document.querySelector('#luvrMonthBody tr[data-employee="1"] [data-date="2026-10-31"]').textContent`),'П');
await ev(`document.querySelector('#luvrMonthBody tr[data-employee="1"] [data-date="2026-10-31"]').click()`);await click('luvrMonthRestore');await wait('document.getElementById("luvrMonthEditor").hidden');await ready();
assert.equal(await ev(`document.querySelector('#luvrMonthBody tr[data-employee="1"] [data-date="2026-10-31"]').textContent`),'1');
// Dynamic day count and visibility are measured, not hard-coded to 31 days.
for(const [year,month,days] of [[2026,2,28],[2024,2,29],[2026,4,30]]){
 await ev(`document.getElementById('luvrMonthYear').value=${year};document.getElementById('luvrMonthNumber').value=${month};document.getElementById('luvrMonthNumber').dispatchEvent(new Event('change'))`);await ready();await click('luvrMonthForm');await ready();
 await ev(`window.scrollTo(0,${box}.getBoundingClientRect().top+scrollY+2)`);await wait(`!${bar}.hidden`);await settle();
 assert.equal(await ev('document.getElementById("luvrMonthHead").children.length'),days+13);assert.equal(await ev(bar+'.scrollWidth'),await ev(box+'.scrollWidth'));await dragEnd();
}
await call('Emulation.setDeviceMetricsOverride',{width:12000,height:768,deviceScaleFactor:1,mobile:false});await settle();assert.equal(await ev(bar+'.hidden'),true);
await call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false});await settle();await click('employeesNavButton');await wait(`${bar}.hidden`);
assert.deepEqual(errors,[]);
const report={result:'PASS',employees:72,checks:['native fixed scrollbar drag without vertical scroll','two-way scroll synchronization','sticky number and name','native vertical wheel and sticky real header','natural bottom scrollbar hides duplicate','resize 1100/1366/1600/1920','real day click and override/reset after scrolling','28/29/30/31 days actual width','no overflow hides scrollbar','tab switch hides scrollbar'],errors};
fs.writeFileSync('C:/Projects/luvr-scroll-browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
