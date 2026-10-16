const {test}=require('node:test'),assert=require('node:assert/strict');
const {createCleanCatalog}=require('../app/static/js/clean_construction_workspace.js');
test('entity-only create, edit and archive contracts',async()=>{
 const calls=[],client=createCleanCatalog(async(url,options)=>{calls.push({url,...options});return {ok:true,json:async()=>({item:{}})};});
 await client.save(null,{name:'Child',category_id:3},{entity_id:12});
 await client.save({entity_id:17,version:4},{name:'Edited',activity_status:'ACTIVE',category_id:null});
 await client.archive({entity_id:17,version:5,is_archived:false});
 await client.archive({entity_id:17,version:6,is_archived:true});
 assert.deepEqual(JSON.parse(calls[0].body),{name:'Child',category_id:3,parent_entity_id:12});
 assert.equal(calls[1].url,'/api/clean-construction-entities/17');
 assert.equal(JSON.parse(calls[1].body).version,4);
 assert.ok(calls[2].url.endsWith('/17/archive'));assert.ok(calls[3].url.endsWith('/17/restore'));
 assert.ok(calls.every(c=>!/(object_id|subobject_id|legacy)/.test(c.body)));
});
test('environment rejection and API errors propagate',async()=>{
 const bad=createCleanCatalog(async()=>({ok:true,json:async()=>({item:{profile:'production',schema:'public',contract:'entity_id'}})}));
 await assert.rejects(bad.verify(),/окружение/);
 const conflict=createCleanCatalog(async()=>({ok:false,json:async()=>({detail:'Version conflict'})}));
 await assert.rejects(conflict.save({entity_id:1,version:1},{name:'x'}),/Version conflict/);
});
test('entity-only roots and children retain hierarchy and sort by entity_id',()=>{
 const {objectCatalogRows}=require('../app/static/js/object_hierarchy.js');
 const roots=[{entity_id:20,name:'A'},{entity_id:10,name:'Z'}];
 const children=[{entity_id:30,parent_entity_id:10,name:'Child'}];
 const rows=objectCatalogRows(roots,children,{sort:'id'});
 assert.deepEqual(rows.map(r=>r.item.entity_id),[10,20]);
 assert.equal(rows[0].children[0].entity_id,30);
 assert.ok(roots.every(r=>r.id===undefined));
});
