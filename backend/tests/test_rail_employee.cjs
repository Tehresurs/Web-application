const {test}=require('node:test');const assert=require('node:assert/strict');
const {railNormalizedName,railEmployeeCandidates}=require('../app/static/js/rail_employee.js');
const {RailTicketController}=require('../app/static/js/rail_tickets.js');
test('passenger matching normalizes case and whitespace without correcting letters',()=>{
 assert.equal(railNormalizedName(' ИВАНОВ \t Иван  Иванович '),'иванов иван иванович');
 assert.notEqual(railNormalizedName('Семён'),railNormalizedName('Семен'));
});
test('similar and duplicate names are suggestions only, not an arbitrary match',()=>{
 const employees=[{id:3,full_name:'Иванов Пётр Иванович'},{id:1,full_name:'Иванов Иван Иванович'},{id:2,full_name:' ИВАНОВ  ИВАН ИВАНОВИЧ '},{id:4,full_name:'Петров Пётр Петрович'}];
 assert.deepEqual(railEmployeeCandidates('Иванов Иван Иванович',employees).map(e=>e.id),[1,2,3]);
 assert.deepEqual(railEmployeeCandidates('',employees),[]);
});
test('manual confirmation sends only explicitly selected employee ID; cancellation sends nothing',async()=>{
 const calls=[];const c=new RailTicketController(async(url,options)=>{calls.push([url,options]);return {item:{id:7,status:'CONFIRMED'}};},()=>{},()=>{});
 c.merge([{id:7,processing_status:'EMPLOYEE_NOT_FOUND'}]);assert.equal(calls.length,0);
 c.employeeSelections.set(7,42);assert.equal(calls.length,0);
 await c.action(7,'confirm',42);
 assert.equal(calls[0][0],'/api/rail-tickets/7/confirm');assert.deepEqual(JSON.parse(calls[0][1].body),{employee_id:42});
});
test('failed confirmation retains manual selection and original ticket',async()=>{
 const errors=[];const c=new RailTicketController(async()=>{throw Error('Сохранение не выполнено');},()=>{},e=>errors.push(e));
 c.merge([{id:7,full_name:'Пассажир'}]);c.employeeSelections.set(7,42);
 await c.action(7,'confirm',42);assert.equal(c.employeeSelections.get(7),42);assert.equal(c.items[0].full_name,'Пассажир');assert.equal(errors.length,1);
});
