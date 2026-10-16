const {test}=require('node:test'),assert=require('node:assert/strict');
const {createCleanAssignmentsClient,cleanCategoryLabel}=require('../app/static/js/clean_assignments_workspace.js');

test('dictionaries and assignment CRUD use only clean-start endpoints and entity_id',async()=>{
 const calls=[];
 const replies=[
  {items:[{id:3,full_name:'Employee'}]},
  {items:[{id:7,name:'PO'}]},
  {items:[{id:9,name:'Parent'},{id:10,name:'Child',parent_id:9}]},
  {items:[{entity_id:12,name:'Root',is_active:true,is_archived:false,parent_is_archived:false,parent_is_active:true}]},
  {items:[],objects_count:0},
  {item:{id:20}},
  {item:{id:20}},
  {deleted:true}
 ];
 const client=createCleanAssignmentsClient(async(url,options={})=>{
  calls.push({url,options});
  return {ok:true,json:async()=>replies.shift()};
 });
 const dictionaries=await client.dictionaries();
 assert.equal(dictionaries.employees[0].id,3);
 assert.equal(dictionaries.entities[0].entity_id,12);
 assert.equal(cleanCategoryLabel(dictionaries.categories[1],new Map(dictionaries.categories.map(x=>[x.id,x]))),'Parent → Child');
 await client.assignments(3);
 await client.save(3,null,{entity_id:12,po_id:7,category_id:10});
 await client.save(3,{id:20},{entity_id:12,po_id:7,category_id:9});
 await client.remove(3,20);
 assert.deepEqual(calls.map(c=>c.url),[
  '/api/clean-construction-entities/employees?archive=active',
  '/api/clean-construction-entities/po-types',
  '/api/clean-construction-entities/categories',
  '/api/clean-construction-entities?archive=active',
  '/api/clean-construction-entities/employees/3/assignments',
  '/api/clean-construction-entities/employees/3/assignments',
  '/api/clean-construction-entities/employees/3/assignments/20',
  '/api/clean-construction-entities/employees/3/assignments/20'
 ]);
 assert.equal(calls[5].options.method,'POST');
 assert.deepEqual(JSON.parse(calls[5].options.body),{entity_id:12,po_id:7,category_id:10});
 assert.equal(calls[6].options.method,'PATCH');
 assert.equal(calls[7].options.method,'DELETE');
 assert.ok(calls.every(call=>!call.url.startsWith('/api/employees')&&!call.url.startsWith('/api/objects')));
 assert.ok(calls.every(call=>!/(object_id|subobject_id|legacy)/.test(call.options.body||'')));
});

test('clean-start request errors propagate',async()=>{
 const client=createCleanAssignmentsClient(async()=>({ok:false,json:async()=>({detail:'source mismatch'})}));
 await assert.rejects(client.assignments(1),/source mismatch/);
});
