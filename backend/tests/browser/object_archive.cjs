// Writes only to the isolated test server on 8881.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const url='http://127.0.0.1:8881',cdp='http://127.0.0.1:9234';
 const api=async(path,method='GET',body)=>{const r=await fetch(url+path,{method,headers:{'Content-Type':'application/json'},body:body&&JSON.stringify(body)});const x=await r.json();assert.equal(r.status,200,JSON.stringify(x));return x;};
 const parent=(await api('/api/objects','POST',{name:'Archive browser '+Date.now()})).object;
 const children=[];for(const name of ['Child A','Child B'])children.push((await api('/api/subobjects','POST',{object_id:parent.id,name})).item);
 const page=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json(),ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),errors=[];
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Page.javascriptDialogOpening')call('Page.handleJavaScriptDialog',{accept:true});};
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const wait=async expression=>{for(let i=0;i<150;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout '+expression);};
 try{
  await call('Page.enable');await call('Runtime.enable');await call('Page.navigate',{url});await wait(`typeof objectArchiveControls==='function'`);
  await ev(`document.getElementById('objectsNavButton').click()`);await wait(`document.querySelector('#objectList [data-record-id="${parent.id}"]')`);
  await ev(`document.querySelector('#objectList [data-record-id="${parent.id}"]').click()`);
  await ev(`document.querySelector('[data-subobject-id="${children[0].id}"] .object-archive-controls button').click()`);
  await wait(`objectSubobjects.find(s=>s.id===${children[0].id}).is_archived`);
  await ev(`document.querySelector('.directory-profile > .object-archive-controls button').click()`);
  await wait(`objectItems.find(o=>o.id===${parent.id}).is_archived`);
  assert.equal(await ev(`!!document.querySelector('#objectList [data-record-id="${parent.id}"]')`),false);
  await ev(`objectArchiveFilter.value='archived';objectArchiveFilter.dispatchEvent(new Event('change'))`);
  await ev(`document.querySelector('#objectList [data-record-id="${parent.id}"]').click()`);
  assert.equal(await ev(`document.querySelectorAll('#objectList [data-subobject-id]').length`),2);
  await ev(`document.querySelector('.directory-profile > .object-archive-controls select').value='COMPLETED';document.querySelector('.directory-profile > .object-archive-controls select').dispatchEvent(new Event('change'))`);
  await wait(`objectItems.find(o=>o.id===${parent.id}).activity_status==='COMPLETED'`);
  await ev(`document.querySelector('.directory-profile > .object-archive-controls button').click()`);
  await wait(`!objectItems.find(o=>o.id===${parent.id}).is_archived`);
  const rows=(await api('/api/subobjects?include_inactive=true')).items.filter(s=>s.object_id===parent.id);
  assert.equal(rows.find(s=>s.id===children[0].id).is_archived,true);assert.equal(rows.find(s=>s.id===children[1].id).is_archived,false);
  await ev(`objectArchiveFilter.value='all';objectArchiveFilter.dispatchEvent(new Event('change'));document.querySelector('#objectList [data-record-id="${parent.id}"]').click()`);
  assert.equal(await ev(`document.querySelectorAll('#objectList [data-subobject-id]').length`),2);
  assert.equal(await ev(`document.querySelector('.directory-profile > .object-archive-controls select').value`),'COMPLETED');
  const directory='C:/Projects/object-archive-review';fs.mkdirSync(directory,{recursive:true});
  await call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false});
  fs.writeFileSync(directory+'/archive.png',Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await call('Page.reload');await wait(`typeof objectArchiveControls==='function'`);await ev(`document.getElementById('objectsNavButton').click()`);await wait(`objectItems.some(o=>o.id===${parent.id})`);
  assert.equal(await ev(`objectItems.find(o=>o.id===${parent.id}).activity_status`),'COMPLETED');
  assert.deepEqual(errors,[]);console.log('Archive browser: child + parent archive, filters, restore, independent child/status, reload OK');
 }finally{ws.close();await fetch(cdp+'/json/close/'+page.id);}
})().catch(e=>{console.error(e);process.exitCode=1;});
