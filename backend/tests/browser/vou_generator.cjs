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
  await ev(`document.getElementById('vouOpenSettings').click()`);
  await wait(`!document.querySelector('#vouSettingsForm button').disabled`);
  assert.equal(await ev(`document.getElementById('vouPage').hidden`),true);
  assert.equal(await ev(`document.getElementById('settingsPage').hidden`),false);
  assert.equal(await ev(`document.querySelectorAll('#vouSettingsForm input').length`),5);
  await ev(`document.getElementById('vouNavButton').click()`);
  await wait(`!document.getElementById('vouArchiveRefresh').disabled`);
  assert.equal(await ev(`!!document.getElementById('vouGenerate')`),true);
  const settings=await ev(`fetch('/api/vou/settings').then(r=>r.json()).then(b=>b.item)`);
  assert.equal(settings.configured,false,'Negative generation check requires empty user settings');
  const countBefore=(await ev(`fetch('/api/vou/reports').then(r=>r.json())`)).items.length;
  await ev(`document.getElementById('vouMonth').value='2026-10';document.getElementById('vouGenerate').click()`);
  await wait(`!document.getElementById('vouGenerate').disabled`);
  const message=await ev(`document.getElementById('vouGenerateStatus').textContent`);
  assert.ok(message.includes('Заполните реквизиты'),message);
  const countAfter=(await ev(`fetch('/api/vou/reports').then(r=>r.json())`)).items.length;
  assert.equal(countAfter,countBefore);
  await ev(`window.__nativeFetch=window.fetch;window.fetch=(url,options)=>{
    if(url==='/api/vou/reports'&&options&&options.method==='POST'){
      return Promise.resolve(new Response(JSON.stringify({detail:{
        message:'Данные ВОУ требуют проверки',
        errors:[
          {code:'POSITION_ORDER_NOT_AGREED',message:'Иванов Иван, 04.10.2026: должность «Инженер СК» не согласована для раздела 1 ВОУ.'},
          {code:'POSITION_ORDER_NOT_AGREED',message:'Петров Пётр, 05.10.2026: должность «Инженер СК» не согласована для раздела 1 ВОУ.'}
        ]
      }}),{status:409,headers:{'Content-Type':'application/json'}}));
    }
    return window.__nativeFetch(url,options);
  }`);
  await ev(`document.getElementById('vouGenerate').click()`);
  await wait(`!document.getElementById('vouGenerate').disabled`);
  const errorSummary=await ev(`document.getElementById('vouGenerateStatus').textContent`);
  const errorDetails=await ev(`document.getElementById('vouWarnings').textContent`);
  assert.ok(errorSummary.includes('Найдено ошибок: 2'),errorSummary);
  assert.ok(errorDetails.includes('Иванов Иван, 04.10.2026'),errorDetails);
  assert.ok(errorDetails.includes('Петров Пётр, 05.10.2026'),errorDetails);
  assert.equal(await ev(`document.getElementById('vouWarnings').dataset.state`),'error');
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log(JSON.stringify({generationButton:true,missingSettingsWarning:message,
    displayedErrorCount:2,displayedEmployeeDates:true,archiveUnchanged:true}));
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log(JSON.stringify({archiveVisible:true,settingsVisible:true,archiveReports:archive.items.length,jsErrors:errors.length,noDatabaseWrites:true}));
 } finally {ws.close();await fetch(cdp+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1});
