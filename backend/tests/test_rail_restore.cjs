const {test}=require('node:test'),assert=require('node:assert/strict');
const {RailTicketController}=require('../app/static/js/rail_tickets.js');
test('restore uses POST and retains exact server state and ticket identity',async()=>{
 const calls=[],errors=[];
 const c=new RailTicketController(async(url,options)=>{calls.push([url,options]);return {item:{id:7,status:'PARSED',processing_status:'READY'}}},()=>{},e=>errors.push(e));
 c.items=[{id:7,status:'ANNULLED'}];
 await c.action(7,'restore');
 assert.equal(calls[0][0],'/api/rail-tickets/7/restore');assert.equal(calls[0][1].method,'POST');
 assert.equal(c.items.length,1);assert.equal(c.items[0].status,'PARSED');assert.equal(c.items[0].processing_status,'READY');assert.deepEqual(errors,[]);
});
test('failed restore leaves annulled ticket visible and permits retry',async()=>{
 const errors=[];const c=new RailTicketController(async()=>{throw Error('Missing snapshot')},()=>{},e=>errors.push(e));
 c.items=[{id:7,status:'ANNULLED'}];await c.action(7,'restore');
 assert.equal(c.items[0].status,'ANNULLED');assert.equal(c.pending.size,0);assert.deepEqual(errors,['Missing snapshot']);
});
