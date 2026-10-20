const assert=require('node:assert/strict');
(async()=>{
 const config=JSON.parse(await new Promise(resolve=>{let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>resolve(s));}));
 const endpoint='http://127.0.0.1:'+config.debug;
 let target;for(let i=0;i<100;i++){try{target=await(await fetch(endpoint+'/json/new?about:blank',{method:'PUT'})).json();break;}catch{await new Promise(r=>setTimeout(r,100));}}
 assert(target,'Browser debugging connection unavailable');
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map();const runtimeErrors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')runtimeErrors.push(m.params.exceptionDetails?.text||'Runtime exception');if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error('Browser expression failed');return r.result.value;};
 const wait=async expression=>{for(let i=0;i<150;i++){try{if(await ev(expression))return;}catch{}await new Promise(r=>setTimeout(r,60));}throw Error('Browser condition timeout: '+expression);};
 try{
 await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
 await call('Page.navigate',{url:config.base+'/'});await wait(`location.pathname==='/login'&&document.getElementById('authLoginForm')?.dataset.authReady==='true'`);
 for(const role of ['manager','engineer']){
 if(role==='manager'){
  await ev(`document.querySelector('[name=login]').value='manager';document.querySelector('[name=password]').value='wrong';document.getElementById('authLoginForm').requestSubmit()`);
  await wait(`!!document.getElementById('authMessage').textContent&&!document.querySelector('button').disabled`);
  assert.equal(await ev(`document.querySelector('[name=password]').value`),'');
 }
 await ev(`document.querySelector('[name=login]').value=${JSON.stringify(role)};document.querySelector('[name=password]').value=${JSON.stringify(config.password)};document.getElementById('authLoginForm').requestSubmit()`);
 await wait(`location.pathname==='/'&&!!document.getElementById('authLogout')`);
 assert.equal(await ev(`document.cookie.includes('tehresurs_session')`),false);
 assert.equal(await ev(`Object.keys(localStorage).concat(Object.keys(sessionStorage)).some(k=>/password|session.token|auth.token|csrf/i.test(k))`),false);
 assert.equal(await ev(`document.getElementById('addEmployeeButton').hasAttribute('data-auth-denied')`),role==='manager');
 assert.equal(await ev(`document.getElementById('vouGenerate').hasAttribute('data-auth-denied')`),role==='manager');
 assert.equal(await ev(`document.getElementById('luvrMonthForm').hasAttribute('data-auth-denied')`),role==='manager');
 assert.equal(await ev(`document.getElementById('railChooseFolder').hasAttribute('data-auth-denied')`),true);
 assert.equal(await ev(`document.getElementById('parseButton').hasAttribute('data-auth-denied')`),true);
 assert.equal(await ev(`document.getElementById('backFromEmployeesButton').hasAttribute('data-auth-denied')`),false);
 assert.equal(await ev(`(async()=>{const b=document.createElement('button');b.id='authDynamicForbidden';b.textContent='\u0421\u043e\u0433\u043b\u0430\u0441\u043e\u0432\u0430\u0442\u044c';document.body.append(b);await new Promise(r=>setTimeout(r,50));return b.hasAttribute('data-auth-denied');})()`),true);
 for(const nav of ['employeesNavButton','objectsNavButton','crewsNavButton','journalNavButton','luvrNavButton','railTicketsNavButton','productionMatrixNavButton','deploymentNavButton','vouNavButton','settingsNavButton']){await ev(`document.getElementById(${JSON.stringify(nav)}).click()`);await new Promise(r=>setTimeout(r,120));}
 assert.equal(await ev(`fetch('/api/employees').then(r=>r.status)`),200);
 if(role==='engineer'){
  assert.equal(await ev(`(async()=>{const f=document.createElement('iframe');document.body.append(f);try{return(await f.contentWindow.fetch(location.origin+'/api/objects',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status;}finally{f.remove();}})()`),403);
  assert.equal(await ev(`fetch('/api/objects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Isolated UI object '+Date.now()})}).then(r=>r.status)`),200);
 }
 assert.equal(await ev(`fetch('/api/deployment/report/export?date=2026-10-18').then(async r=>r.ok&&(new Uint8Array(await r.arrayBuffer()))[0]===80)`),true);
 assert.equal(await ev(`fetch('/api/unreviewed',{method:'POST'}).then(r=>r.status)`),403);
 assert.equal(await ev(`fetch('/api/employees/1',{method:'DELETE'}).then(r=>r.status)`),403);
 if(role==='manager')assert.equal(await ev(`fetch('/api/objects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'must not exist'})}).then(r=>r.status)`),403);
 await ev(`document.getElementById('authLogout').click()`);await wait(`location.pathname==='/login'&&document.getElementById('authLoginForm')?.dataset.authReady==='true'`);
 assert.equal(await ev(`fetch('/api/employees').then(r=>r.status)`),401);
 }
 assert.equal(runtimeErrors.length,0,'Uncaught browser errors during role navigation');
 console.log(JSON.stringify({browserLoginBothRoles:true,invalidPassword:true,noSessionRedirect:true,logout:true,httpOnly:true,roleControls:true,excelBothRoles:true,directDenials:true}));
 }finally{try{await call('Browser.close');}catch{}ws.close();}
})().catch(error=>{console.error('Isolated browser authorization check failed: '+error.message);process.exitCode=1});
