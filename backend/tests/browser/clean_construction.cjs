const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
(async()=>{
 const watchdog=setTimeout(()=>{console.error('Browser scenario did not finish');process.exit(1);},60000);
 const base=process.argv[2],url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert.ok(!['8000','8001'].includes(url.port));
 const chrome=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(fs.existsSync);assert.ok(chrome);
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'clean-catalog-browser-'));
 const proc=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${dir}`,'about:blank'],{windowsHide:true,stdio:['ignore','ignore','pipe']});
 let chromeLog='';proc.stderr.on('data',b=>{chromeLog+=b.toString();});
 let ws;
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 try{
  for(let i=0;i<100&&!fs.existsSync(path.join(dir,'DevToolsActivePort'));i++)await sleep(100);
  const port=fs.readFileSync(path.join(dir,'DevToolsActivePort'),'utf8').split('\n')[0];
  let page;
  for(let i=0;i<50;i++){try{page=await(await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'})).json();break;}catch(e){if(i===49)throw e;await sleep(200);}}
  ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
  let id=0;const pending=new Map(),errors=[];
  ws.addEventListener('close',()=>{for(const p of pending.values())p.reject(Error('Chrome connection closed: '+chromeLog));pending.clear();});
  const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Page.javascriptDialogOpening'){if(m.params.type==='alert')errors.push(m.params.message);call('Page.handleJavaScriptDialog',{accept:true});}};
  const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const wait=async expression=>{for(let i=0;i<100;i++){if(await ev(expression))return;await sleep(100);}throw Error('Timeout '+expression+' errors='+JSON.stringify(errors));};
  await call('Page.enable');await call('Runtime.enable');await call('Page.navigate',{url:base+'/api/clean-construction-entities/workspace'});
  await wait("document.querySelector('#objectCount')?.textContent.includes('Записей')");
  const rows="[...document.querySelectorAll('#objectList tr[data-entity-id]')]";
  const find=name=>`${rows}.find(r=>r.querySelector('.object-catalog-name').textContent===${JSON.stringify(name)})`;
  async function create(name,parent){
   await ev(parent?`${find(parent)}.querySelector('.add-subobject-directory').click()`:"document.getElementById('addDirectoryObjectButton').click()");
   await ev(`document.getElementById('objectDirectoryNameInput').value=${JSON.stringify(name)};document.getElementById('cleanCategory').selectedIndex=1;document.getElementById('objectDirectoryModalSave').click()`);
   await wait(`${find(name)}!=null`);
  }
  await create('Browser root');await create('Browser child','Browser root');
  const eid=await ev(`${find('Browser child')}.dataset.entityId`);
  await ev(`${find('Browser child')}.querySelector('.edit-subobject-directory').click();document.getElementById('objectDirectoryNameInput').value='Browser edited';document.getElementById('cleanStatus').value='SUSPENDED';document.getElementById('objectDirectoryModalSave').click()`);
  await wait(`${find('Browser edited')}!=null`);
  await ev(`${find('Browser edited')}.querySelector('.make-standalone-preview').click();document.getElementById('identityStandaloneCheck').click()`);
  await wait(`${find('Browser edited')}?.classList.contains('object-catalog-root-row')`);
  await ev(`${find('Browser edited')}.querySelector('.promote-preview').click()`);
  const rootId=await ev(`${find('Browser root')}.dataset.entityId`);
  await ev(`document.getElementById('identityPromoteParent').value=${JSON.stringify(rootId)};document.getElementById('identityPromoteCheck').click()`);
  await wait(`${find('Browser edited')}?.classList.contains('object-catalog-child-row')`);
  await ev(`${find('Browser edited')}.querySelector('.archive-subobject-directory').click()`);
  await ev("document.querySelector('[data-object-view=archived]').click()");
  await wait(`${find('Browser edited')}?.querySelector('.archive-subobject-directory').textContent.includes('Восстановить')`);
  await ev(`${find('Browser edited')}.querySelector('.archive-subobject-directory').click()`);
  await ev("document.querySelector('[data-object-view=all]').click()");
  await wait(`${find('Browser edited')}?.querySelector('.archive-subobject-directory').textContent==='В архив'`);
  assert.equal(await ev(`${find('Browser edited')}.dataset.entityId`),eid);
  assert.equal(await ev(`${rows}.filter(r=>r.dataset.entityId===${JSON.stringify(eid)}).length`),1);
  const saved=await(await fetch(base+'/api/clean-construction-entities/'+eid)).json();
  assert.equal(saved.item.parent_entity_id,Number(rootId));assert.equal(saved.item.activity_status,'SUSPENDED');
  assert.ok(saved.item.category_id);assert.equal(saved.item.is_archived,false);
  assert.deepEqual(errors,[]);console.log('Browser lifecycle passed');
 }finally{clearTimeout(watchdog);if(ws)ws.close();proc.kill();await sleep(600);try{fs.rmSync(dir,{recursive:true,force:true});}catch{}}
})().catch(e=>{console.error(e);process.exitCode=1;});
