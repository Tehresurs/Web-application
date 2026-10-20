const {test}=require('node:test');const assert=require('node:assert/strict');
const {ProductionMatrixController,pmPayload,pmCategories,pmAmount}=require('../app/static/js/production_matrix.js');
const cell={employee_id:17,edit_target:{scope:'PLAN',period_key:'arrival:1',basis_revision:'1',fact_id:null,assignment_item_id:4,effective_from:'2026-10-05',fields:{CATEGORY:{version:0},CONTROL_MODE:{version:3},PO:{version:2}}}};
test('personal matrix keeps employee filter on load and after saving',async()=>{
 const calls=[];const c=new ProductionMatrixController(async(url)=>{calls.push(url);return url.includes('categories')?{items:[]}:{item:{employees:[]}};},()=>{},()=>{},17);
 await c.load(2026,10);await c.change(cell,'CONTROL_MODE','INSPECTION');
 assert.deepEqual(calls.filter(url=>url.startsWith('/api/production-matrix?')),
  ['/api/production-matrix?year=2026&month=10&employee_id=17','/api/production-matrix?year=2026&month=10&employee_id=17']);
});
test('matrix uses separate versions for category and control mode and sends only allowed values',()=>{
 const category=pmPayload(cell,'CATEGORY','90');assert.equal(category.category_id,90);assert.equal(category.version,0);assert.equal(category.assignment_item_id,4);assert.equal(category.effective_from,'2026-10-05');assert.ok(!('control_mode' in category));assert.ok(!('fields' in category));
 const mode=pmPayload(cell,'CONTROL_MODE','OPERATIONAL');assert.equal(mode.version,3);assert.ok(!('category_id' in mode));
});
test('cameral and readonly cells cannot be patched',()=>{assert.throws(()=>pmPayload({},'CATEGORY',1));assert.throws(()=>pmPayload(cell,'CONTROL_MODE','CAMERAL'));assert.throws(()=>pmPayload(cell,'object_id',2));});
test('dictionary flattening keeps children and does not duplicate categories',()=>{assert.deepEqual(pmCategories([{id:1,children:[{id:2}]},{id:2}]).map(x=>x.id),[1,2]);});
test('hundredths are formatted without calculating distribution',()=>{assert.equal(pmAmount(33),'0,33');assert.equal(pmAmount(34),'0,34');assert.equal(pmAmount(0),'0,00');assert.equal(pmAmount(null),'—');});
test('matrix load uses existing API and retains exact backend values',async()=>{
 const data={employees:[{totals:{available_cents:17}}]},calls=[];const c=new ProductionMatrixController(async url=>{calls.push(url);return url.includes('categories')?{items:[]}:{item:data};},()=>{},()=>{});
 await c.load(2026,10);assert.equal(c.data,data);assert.ok(calls.includes('/api/production-matrix?year=2026&month=10'));assert.equal(c.busy,false);
});
test('late month response cannot replace selected month',async()=>{
 let release;const slow=new Promise(r=>release=r);const c=new ProductionMatrixController(async url=>url.includes('categories')?{items:[]}:url.endsWith('month=10')?slow:{item:{month:11}},()=>{},()=>{});
 const first=c.load(2026,10);await c.load(2026,11);release({item:{month:10}});await first;assert.equal(c.data.month,11);
});
test('editing uses employee id then reloads server result',async()=>{
 const calls=[];const c=new ProductionMatrixController(async(url,method,payload)=>{calls.push({url,method,payload});return {item:{year:2026,month:10}};},()=>{},()=>{});c.selection={year:2026,month:10};
 assert.equal(await c.change(cell,'CONTROL_MODE','INSPECTION'),true);assert.equal(calls[0].url,'/api/employees/17/production-matrix-overrides');assert.equal(calls[0].method,'PATCH');assert.equal(calls[0].payload.version,3);assert.equal(calls[1].url,'/api/production-matrix?year=2026&month=10');
});
test('conflict reports error and refreshes versions without retrying patch',async()=>{
 const errors=[],calls=[];const c=new ProductionMatrixController(async(url,method)=>{calls.push(method||'GET');if(method==='PATCH')throw Error('Version conflict');return {item:{updated:true}};},()=>{},m=>errors.push(m));c.selection={year:2026,month:10};
 assert.equal(await c.change(cell,'CATEGORY',1),false);assert.deepEqual(calls,['PATCH','GET']);assert.equal(c.data.updated,true);assert.deepEqual(errors,['Version conflict']);
});
test('invalid month sends no request',async()=>{let called=false;const c=new ProductionMatrixController(async()=>{called=true;},()=>{},()=>{});await c.load(2026,13);assert.equal(called,false);});
test('GEODETIC selection requires backend permission for the employee',()=>{
 assert.throws(()=>pmPayload(cell,'CONTROL_MODE','GEODETIC'));
 const geo={...cell,allowed_control_modes:['INSPECTION','OPERATIONAL','GEODETIC']};
 assert.equal(pmPayload(geo,'CONTROL_MODE','GEODETIC').control_mode,'GEODETIC');
 assert.throws(()=>pmPayload(geo,'CONTROL_MODE','CAMERAL'));
});

test('PO uses its own version and a positive directory id',()=>{
 const p=pmPayload(cell,'PO','2');assert.equal(p.po_id,2);assert.equal(p.version,2);
 assert.equal(p.field_name,'PO');assert.ok(!('category_id' in p));assert.ok(!('control_mode' in p));
 for(const invalid of ['',0,-1,'abc'])assert.throws(()=>pmPayload(cell,'PO',invalid));
});
