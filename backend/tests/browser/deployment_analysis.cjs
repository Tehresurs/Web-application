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
  await ev(`document.getElementById('deploymentNavButton').click();document.getElementById('analysisDate').value='2026-10-12';document.getElementById('deploymentAnalysisTab').click()`);
  await wait(`!document.getElementById('analysisContent').hidden && document.querySelectorAll('#deploymentAnalysis svg').length===3`);
  const expected=await ev(`fetch('/api/deployment/analysis?date=2026-10-12').then(r=>r.json()).then(r=>r.item)`);
  assert.equal(expected.history.length,7);assert.equal(expected.history[0].date,'2026-10-05');assert.equal(expected.history[6].date,'2026-10-11');
  assert.equal(await ev(`document.querySelectorAll('#analysisMetrics .da-metric').length`),6);
  assert.equal(await ev(`document.querySelectorAll('#analysisStaff tr').length`),expected.staffing.length+1);
  assert.equal(await ev(`document.querySelector('[data-metric="total"] strong').textContent`),String(expected.production.total));
  assert.equal(await ev(`document.querySelectorAll('#deploymentAnalysis svg').length`),3);
  const pid=expected.staffing[0].position_id;
  await ev(`document.getElementById('analysisPosition').value='${pid}';document.getElementById('analysisPosition').dispatchEvent(new Event('change'))`);
  assert.equal(await ev(`document.getElementById('analysisPosition').value`),String(pid));
  const lines=await ev(`document.querySelectorAll('#analysisChartProduction polyline').length`);
  await ev(`document.querySelector('[data-line="objects"]').click()`);
  assert.ok(await ev(`document.querySelectorAll('#analysisChartProduction polyline').length`)<lines);
  for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
   await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'));
   fs.mkdirSync('C:/Projects/deployment-analysis-review',{recursive:true});
   fs.writeFileSync(`C:/Projects/deployment-analysis-review/${width}x${height}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  }
  await call('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});
  await ev(`document.getElementById('analysisChartStaff').scrollIntoView({block:'start'})`);
  fs.writeFileSync('C:/Projects/deployment-analysis-review/charts.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await ev(`document.getElementById('analysisDate').value='2026-11-03';document.getElementById('analysisRefresh').click()`);
  await wait(`document.getElementById('analysisWindow').textContent.includes('2026-10-27')`);
  assert.ok(await ev(`document.getElementById('analysisWindow').textContent.includes('2026-11-02')`));
  await ev(`document.getElementById('analysisDate').value='2099-01-01';document.getElementById('analysisRefresh').click()`);
  await wait(`!document.getElementById('analysisContent').hidden && document.getElementById('analysisWindow').textContent.includes('2098-12-25')`);
  assert.equal(await ev(`document.querySelector('[data-metric="total"] strong').textContent`),'—');
  await ev(`document.getElementById('deploymentReportTab').click()`);
  assert.equal(await ev(`document.getElementById('deploymentAnalysis').hidden`),true);
  await wait(`!document.getElementById('deploymentExport').disabled`);
  assert.equal(await ev(`document.querySelectorAll('#deploymentHead th').length`),7);
  assert.deepEqual(errors,[]);console.log('PASS analysis: metrics/table match API, seven days, three charts, position selector, series toggle, month boundary, missing month, original report, three viewports, no JS exceptions');
 }finally{ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
