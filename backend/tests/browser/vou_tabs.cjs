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
  assert.equal(await ev(`document.getElementById('vouCreatePanel').hidden`),false);
  assert.equal(await ev(`document.getElementById('vouArchivePanel').hidden`),true);
  await ev(`document.getElementById('vouMonth').value='2026-09';document.getElementById('vouArchiveTab').click()`);
  await wait(`!document.getElementById('vouArchiveRefresh').disabled`);
  assert.equal(await ev(`document.getElementById('vouCreatePanel').hidden`),true);
  assert.equal(await ev(`document.getElementById('vouArchivePanel').hidden`),false);
  assert.equal(await ev(`document.getElementById('vouArchiveTab').getAttribute('aria-selected')`),'true');
  await ev(`document.getElementById('vouArchiveTab').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))`);
  assert.equal(await ev(`document.getElementById('vouPersonnelPanel').hidden`),false);
  await ev(`document.getElementById('vouPersonnelTab').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))`);
  assert.equal(await ev(`document.getElementById('vouCreatePanel').hidden`),false);
  assert.equal(await ev(`document.getElementById('vouMonth').value`),'2026-09');
  assert.equal(await ev(`document.activeElement.id`),'vouCreateTab');
  console.log(JSON.stringify({separateArchiveTab:true,keyboardNavigation:true,periodPreserved:true}));

  await ev(`document.getElementById('vouOpenSettings').click()`);
  await wait(`!document.querySelector('#vouSettingsForm button').disabled`);
  assert.equal(await ev(`document.getElementById('vouPage').hidden`),true);
  assert.equal(await ev(`document.getElementById('settingsPage').hidden`),false);
  assert.equal(await ev(`document.querySelectorAll('#vouSettingsForm input').length`),5);
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log(JSON.stringify({archiveVisible:true,settingsVisible:true,archiveReports:archive.items.length,jsErrors:errors.length,noWrites:true}));
 } finally {ws.close();await fetch(cdp+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1});
