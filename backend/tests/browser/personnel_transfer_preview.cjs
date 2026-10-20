const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const [port,url,out]=process.argv.slice(2);let ws;const errors=[],network=[];
try{const pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((ok,bad)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',bad,{once:true})});let seq=0;const pending=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Network.requestWillBeSent')network.push(m.params.request.url)};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Page.navigate',{url});
for(let i=0;i<100;i++){if(await ev('Boolean(document.getElementById("history")?.children.length)'))break;await new Promise(r=>setTimeout(r,50))}
assert.equal(await ev('document.querySelectorAll("#history tr").length'),1);
await ev('document.getElementById("open").click();document.getElementById("position").value="2";document.getElementById("date").value="2030-02-01";document.getElementById("form").requestSubmit()');
assert.equal(await ev('document.getElementById("dialog").open'),true);assert.equal(await ev('document.getElementById("submit").textContent'), 'Подтвердить перевод в макете');
await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
fs.writeFileSync(out+'/transfer-dialog.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
await ev('document.getElementById("form").requestSubmit()');assert.equal(await ev('document.querySelectorAll("#history tr").length'),2);assert.equal(await ev('document.getElementById("current").textContent'),'Инженер ПИЛ');
assert.match(await ev('document.getElementById("history").textContent'),/Запланирован/);
await ev('document.getElementById("open").click();document.getElementById("date").value="2029-12-01";document.getElementById("form").requestSubmit()');assert.match(await ev('document.getElementById("error").textContent'),/Ранние сведения/);await ev('document.getElementById("cancel").click()');
await ev('document.getElementById("role").value="office";document.getElementById("role").dispatchEvent(new Event("change"))');assert.equal(await ev('document.getElementById("open").hidden'),true);
const geometry=[];for(const [width,height] of [[1440,1000],[390,844]]){await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<600});await new Promise(r=>setTimeout(r,100));const row=await ev('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})');assert.ok(row.scrollWidth<=row.width+1);geometry.push(row);fs.writeFileSync(out+`/history-${width}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'))}
assert.deepEqual(errors,[]);assert.ok(network.every(u=>!/^https?:/.test(u)));
fs.writeFileSync(out+'/browser.json',JSON.stringify({success:true,assertions:'future transfer, two-stage confirmation, unknown-date refusal, office view, responsive layout, no network HTTP, no JS exceptions',geometry,network,errors},null,2));
console.log('Personnel preview browser checks passed');await call('Browser.close');
}catch(e){console.error(e);process.exitCode=1}finally{if(ws)ws.close()}})();
