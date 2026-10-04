const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const pages=await(await fetch('http://127.0.0.1:9234/json')).json();
 const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let id=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
 const ev=async expression=>{const r=await new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}));});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 try{
  const sticky=()=>ev(`(()=>{const row=document.querySelector('#luvrMonthBody tr');return [row.children[0],row.children[1]].map(c=>({left:c.getBoundingClientRect().left,position:getComputedStyle(c).position}));})()`);
  await ev(`document.querySelector('.luvr-month-scroll').scrollLeft=0`);const initial=await sticky();
  await ev(`document.querySelector('.luvr-month-scroll').scrollLeft=100000`);const shifted=await sticky();
  shifted.forEach((c,i)=>{assert.equal(c.position,'sticky');assert.ok(Math.abs(c.left-initial[i].left)<1);});
  assert.equal(await ev(`getComputedStyle(document.querySelector('#luvrMonthHead th')).position`),'sticky');
  const view=await ev(`(()=>{const foot=document.querySelector('#luvrMonthTotals');return {rows:foot.children.length,title:foot.querySelector('th').textContent,order:Array.from(document.querySelectorAll('#luvrMonthBody tr'),r=>Number(r.dataset.employee)),names:Array.from(document.querySelectorAll('#luvrMonthBody .luvr-employee-link'),b=>b.textContent),daily:Array.from(foot.querySelectorAll('[data-total-date]'),c=>Number(c.textContent.replace(',','.'))),totals:Object.fromEntries(Array.from(foot.querySelectorAll('[data-total]'),c=>[c.dataset.total,Number(c.textContent.replace(',','.'))]))};})()`);
  assert.equal(view.rows,1);assert.equal(view.title,'Итого');assert.equal(view.order.length,67);
  await ev(`document.querySelector('#luvrMonthBody .luvr-employee-link').click()`);
  for(let i=0;i<100;i++){if(await ev('!document.getElementById("employeeModal").hidden'))break;await new Promise(r=>setTimeout(r,50));}
  assert.equal(await ev('document.getElementById("employeeNameInput").value'),view.names[0].replace(' (архив)',''));
  const response=await fetch('http://127.0.0.1:8000/api/luvr/month/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({year:2026,month:10,employee_ids:view.order})});
  assert.equal(response.status,200);
  const folder='C:/Projects/luvr-compact-check';fs.mkdirSync(folder,{recursive:true});
  fs.writeFileSync(folder+'/final.xlsx',Buffer.from(await response.arrayBuffer()));fs.writeFileSync(folder+'/web.json',JSON.stringify(view));
  console.log('PASS: one footer, selected order, employee card, API export saved for cell-by-cell comparison');
 }finally{ws.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
