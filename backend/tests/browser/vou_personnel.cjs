const assert=require('node:assert/strict');
(async()=>{
 const cdp='http://127.0.0.1:9234';
 const page=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();
 const ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<150;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 try {
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Page.navigate',{url:'http://127.0.0.1:8001/'});
  await wait(`typeof showMainSection==='function' && document.getElementById('vouNavButton')`);
  await ev(`document.getElementById('vouNavButton').click()`);
  await wait(`!document.getElementById('vouArchiveRefresh').disabled`);
  assert.equal(await ev(`document.getElementById('vouPage').hidden`),false);
  assert.equal(await ev(`document.getElementById('productionMatrixPage').hidden`),true);
  const archive=await ev(`fetch('/api/vou/reports').then(r=>r.json())`);
  assert.equal(archive.status,'ok');
  await ev(`document.getElementById('vouPersonnelTab').click()`);
  await wait(`!document.getElementById('vouPersonnelScroll').hidden`);
  const check=await ev(`(async()=>{
    const archive=await fetch('/api/vou/reports').then(r=>r.json());
    const report=await fetch('/api/vou/reports/'+archive.items[0].id).then(r=>r.json()).then(b=>b.item);
    const blocks=report.verification.com.fresh_excel.readback_blocks;
    const grid=Object.values(blocks)[0];
    const length=new Date(Date.UTC(report.year,report.month,0)).getUTCDate();
    const columns=[0,1,2,3,...Array.from({length},(_,i)=>4+i),35,36];
    let mismatches=0,compared=0;
    grid.forEach((values,index)=>{
      if(values.every(v=>v==null||v===''))return;
      const row=document.querySelector('#vouPersonnelRows tr[data-excel-row="'+(index+14)+'"]');
      if(!row){mismatches++;return;}
      columns.forEach((source,col)=>{
        const value=values[source];
        const expected=typeof value==='number'?value.toLocaleString('ru-RU',{minimumFractionDigits:source===35?2:0,maximumFractionDigits:2}):String(value??'');
        compared++;if(row.children[col].textContent!==expected)mismatches++;
      });
    });
    const dk=report.verification.dk_cells.map(c=>{
      const excelRow=Number(c.address.match(/[0-9]+/)[0]);const day=Number(c.date.slice(-2));
      return document.querySelector('#vouPersonnelRows tr[data-excel-row="'+excelRow+'"]')?.children[3+day]?.textContent;
    });
    return {compared,mismatches,dk,total:document.getElementById('vouPersonnelTotal').textContent,headers:document.querySelectorAll('#vouPersonnelHead th').length};
  })()`);
  assert.equal(check.mismatches,0);
  assert.ok(check.compared>1000);
  assert.ok(check.dk.every(v=>v===''));
  assert.equal(check.headers,37);
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  const shot=await call('Page.captureScreenshot',{format:'png'});
  const fs=require('node:fs'),path=require('node:path');
  fs.writeFileSync(path.resolve(__dirname,'../../output/vou/vou-personnel-ui.png'),Buffer.from(shot.data,'base64'));
  console.log(JSON.stringify(check));
  if (archive.items.length>1) {
    await ev(`document.getElementById('vouArchiveTab').click()`);
    await wait(`!document.getElementById('vouArchiveRefresh').disabled`);
    await ev(`document.querySelector('#vouArchiveRows tr:last-child button').click()`);
    const older=archive.items[archive.items.length-1].id;
    await wait(`!document.getElementById('vouPersonnelScroll').hidden && document.getElementById('vouPersonnelDownload').href.includes('${older}')`);
    assert.equal(await ev(`document.getElementById('vouPersonnelPanel').hidden`),false);
    console.log('Archived Personnel view OK');
  }


  await ev(`document.getElementById('settingsNavButton').click()`);
  await wait(`!document.querySelector('#vouSettingsForm button').disabled`);
  assert.equal(await ev(`document.getElementById('vouPage').hidden`),true);
  assert.equal(await ev(`document.getElementById('settingsPage').hidden`),false);
  assert.equal(await ev(`document.querySelectorAll('#vouSettingsForm input').length`),5);
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log(JSON.stringify({archiveVisible:true,settingsVisible:true,archiveReports:archive.items.length,jsErrors:errors.length,noWrites:true}));
 } finally {ws.close();await fetch(cdp+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1});
