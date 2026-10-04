const {test}=require('node:test'),assert=require('node:assert/strict');
const {LuvrHistoryController}=require('../app/static/js/luvr_history.js');
const {RailTicketController}=require('../app/static/js/rail_tickets.js');
test('joint delete uses explicit flag scoped to the selected movement and employee',async()=>{
 const calls=[];const c=new LuvrHistoryController(async(...args)=>{calls.push(args);return {items:[],ticket_id:5};},()=>{},()=>{});c.open(17);
 assert.equal(await c.mutate('movements','DELETE',null,42,true),true);
 assert.deepEqual(calls[0],['/api/employees/17/luvr/movements/42?delete_ticket=true','DELETE',null]);
 assert.equal(calls.length,4);
});
test('SELF delete keeps original URL',async()=>{const calls=[];const c=new LuvrHistoryController(async(...a)=>{calls.push(a);return {items:[]};},()=>{},()=>{});c.open(17);await c.mutate('movements','DELETE',null,42);assert.equal(calls[0][0],'/api/employees/17/luvr/movements/42');});
test('deletion invalidates exactly one ticket, not all pages from same file',()=>{
 const c=new RailTicketController(()=>{},()=>{},()=>{});c.items=[{id:1,source_filename:'two.pdf'},{id:2,source_filename:'two.pdf'}];c.batchItems=[...c.items];c.removeDeletedTicket(1);
 assert.deepEqual(c.items.map(t=>t.id),[2]);assert.deepEqual(c.batchItems.map(t=>t.id),[2]);
 c.merge([{id:1},{id:3,source_filename:'two.pdf'}]);assert.deepEqual(c.items.map(t=>t.id),[2,3]);
});
test('late upload response cannot reintroduce a deleted ticket',async()=>{
 let done;const c=new RailTicketController(()=>new Promise(r=>done=r),()=>{},()=>{});
 const file=new Blob(['pdf']);Object.defineProperty(file,'name',{value:'two.pdf'});const upload=c.upload([file]);c.removeDeletedTicket(1);
 done({items:[{id:1},{id:2}]});await upload;assert.deepEqual(c.items.map(t=>t.id),[2]);assert.deepEqual(c.batchItems.map(t=>t.id),[2]);
});
