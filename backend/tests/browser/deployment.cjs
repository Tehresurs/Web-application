// Read-only browser verification against the running application.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=process.env.MODAL_CDP_URL||'http://127.0.0.1:9234';
 const page=await(await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<200;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 try{
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Page.navigate',{url:process.env.MODAL_APP_URL||'http://127.0.0.1:8000/'});
  await wait(`typeof initDeployment==='function'`);
  await ev(`document.getElementById('deploymentDate').value='2026-10-12';document.getElementById('deploymentNavButton').click()`);
  await wait(`!document.getElementById('deploymentExport').disabled`);
  assert.equal(await ev(`document.querySelectorAll('#deploymentHead th').length`),7);
  const expected=await ev(`fetch('/api/deployment/report?date=2026-10-12').then(r=>r.json()).then(r=>r.item)`);
  assert.equal(await ev(`document.querySelectorAll('#deploymentRows tr').length`),expected.rows.length);
  assert.ok(await ev(`document.getElementById('deploymentTotals').textContent.includes('специалистов СК на объектах: '+${expected.totals.specialists})`));
  for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'));
   fs.mkdirSync('C:/Projects/deployment-review',{recursive:true});
   fs.writeFileSync(`C:/Projects/deployment-review/${width}x${height}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  }
  await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:'C:\\Projects\\deployment-review'});
  await call('Page.setDownloadBehavior',{behavior:'allow',downloadPath:'C:\\Projects\\deployment-review'});
  await ev(`document.getElementById('deploymentExport').click()`);
  for(let i=0;i<200&&!fs.existsSync('C:/Projects/deployment-review/Расстановка_2026-10-12.xlsx');i++)await new Promise(r=>setTimeout(r,100));
  assert.ok(fs.existsSync('C:/Projects/deployment-review/Расстановка_2026-10-12.xlsx'));
  await ev(`document.getElementById('deploymentDate').value='2099-01-01';document.getElementById('deploymentDate').dispatchEvent(new Event('change'));document.getElementById('deploymentRefresh').click()`);
  await wait(`document.getElementById('deploymentStatus').textContent.includes('не сформирован')`);
  assert.equal(await ev(`document.getElementById('deploymentExport').disabled`),true);
  for(const nav of ['employeesNavButton','luvrNavButton','railTicketsNavButton','productionMatrixNavButton','processingNavButton']){
   await ev(`document.getElementById('${nav}').click()`);
   assert.equal(await ev(`document.getElementById('deploymentPage').hidden`),true);
  }
  assert.deepEqual(errors,[]);console.log('PASS deployment: live rows/totals, seven columns, three viewports, Excel download, missing month, navigation, no JS exceptions');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
