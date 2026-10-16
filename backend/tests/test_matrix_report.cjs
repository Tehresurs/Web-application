const test=require('node:test');
const assert=require('node:assert/strict');
const {ReportSaveController}=require('../app/static/js/report_save.js');
const el=()=>({disabled:true,hidden:false,textContent:'',addEventListener(){}});
function controller(fetchRequest){return new ReportSaveController({button:el(),retryButton:el(),message:el(),fetchRequest,ready:()=>true,onState:()=>{}});}
function report(){return {source_path:'C:/single/report.docx',employee_id:7,employee_status:'found',entity_id:10,object_status:'found',assignments:{},matrix_context:{employee_id:7,date:'2026-10-15',replace_fact_id:42,replace_source_sha256:'abc'}};}
test('matrix selection is passed as a guard, never as an invented report date',()=>{
 const c=controller();const p=c.payload(report());
 assert.equal(p.expected_employee_id,7);
 assert.equal(p.expected_report_date,'2026-10-15');
 assert.equal(p.replace_fact_id,42);
 assert.equal(p.replace_source_sha256,'abc');
 assert.ok(!Object.hasOwn(p,'report_date'));
});
test('replacement requires reviewed payload and explicit confirmation before request',async()=>{
 const calls=[];const c=controller(async(path,options)=>{calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({saved:true,results:[{id:99}]})};});
 const r=report(),payload=c.payload(r);
 global.window={processingReports:[r],confirm:()=>false};
 try{
  await assert.rejects(c.request('/api/daily-control-results',payload));
  assert.equal(calls.length,0);
  r.matrix_preview_signature=JSON.stringify(payload);r.matrix_preview_token='reviewed';
  await assert.rejects(c.request('/api/daily-control-results',payload));
  assert.equal(calls.length,0);
  window.confirm=()=>true;
  const result=await c.request('/api/daily-control-results',payload);
  assert.equal(result.results[0].id,99);
  assert.equal(calls[0].confirm_replacement,true);
  assert.equal(calls[0].replacement_token,'reviewed');
 }finally{delete global.window;}
});
