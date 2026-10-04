const {test}=require('node:test'),assert=require('node:assert/strict');
const {LuvrCalendarController,LUVR_CALENDAR_VALUES}=require('../app/static/js/luvr_calendar.js');
const harness=request=>{const errors=[];return {c:new LuvrCalendarController(request,()=>{},m=>errors.push(m)),errors};};
const day={date:'2026-10-15',override_id:7};
test('calendar selection is read-only and month values are not converted through UTC',async()=>{
 const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{days:[]}};});
 await c.select(25,'2026-10');assert.deepEqual(calls,[['/api/employees/25/luvr/calendar?year=2026&month=10']]);
});
test('edit day uses existing override API with full value and comment',async()=>{
 const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{days:[]}};});await c.select(25,'2026-10');
 await c.change(day,'DOWNTIME',' отпуск ');
 assert.deepEqual(calls[1],['/api/employees/25/luvr/day-overrides','POST',{work_date:'2026-10-15',value:'DOWNTIME',comment:'отпуск'}]);
 assert.ok(calls[2][0].includes('/calendar?'));assert.ok(calls.every(x=>!x[0].includes('/movements')));
});
test('restore deletes only specific override and refreshes calculation',async()=>{
 const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{}};});await c.select(25,'2026-10');await c.change(day,null,'',true);
 assert.deepEqual(calls[1],['/api/employees/25/luvr/day-overrides/7','DELETE',undefined]);assert.equal(calls.length,3);
});
test('all seven codes retain display labels, including explicit empty',()=>{
 assert.deepEqual(LUVR_CALENDAR_VALUES,{FULL:'1',HALF:'0,5',TRAVEL:'Д',OFF_SHIFT:'МВ',DOWNTIME:'П',DISMISSED:'Уволен',EMPTY:'Пусто'});
});
test('late response for another employee cannot replace current calendar',async()=>{
 let old;const {c}=harness(url=>url.includes('/1/')?new Promise(r=>old=r):Promise.resolve({item:{employee_id:2}}));
 const first=c.select(1,'2026-10');await c.select(2,'2026-11');old({item:{employee_id:1}});await first;assert.equal(c.data.employee_id,2);
});
test('mutation of old employee cannot refresh or replace newly selected calendar',async()=>{
 let done;const calls=[];const {c}=harness((...args)=>{calls.push(args);return args[1]==='POST'?new Promise(r=>done=r):Promise.resolve({item:{employee_id:args[0].includes('/1/')?1:2}});});
 await c.select(1,'2026-10');const change=c.change(day,'FULL');await c.select(2,'2026-11');done({status:'ok'});assert.equal(await change,false);assert.equal(c.data.employee_id,2);assert.equal(calls.length,3);
});
test('double save produces one override request',async()=>{
 let done,count=0;const {c}=harness(async(url,method)=>{if(method){count++;await new Promise(r=>done=r);}return {item:{}};});await c.select(1,'2026-10');const a=c.change(day,'EMPTY');assert.equal(await c.change(day,'FULL'),false);done();await a;assert.equal(count,1);
});
test('failed write preserves data and reports failure; retry remains possible',async()=>{
 const {c,errors}=harness(async(url,method)=>{if(method)throw Error('Не сохранено');return {item:{days:[day]}};});await c.select(1,'2026-10');assert.equal(await c.change(day,'FULL'),false);assert.equal(c.busy,false);assert.deepEqual(c.data.days,[day]);assert.deepEqual(errors,['Не сохранено']);
});
test('invalid month, absent selection and invalid code send no mutation',async()=>{
 const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{}};});await c.select(1,'2026-13');await c.change(day,'FULL');assert.equal(calls.length,0);
 await c.select(1,'2026-10');await c.change(day,'0.5');assert.equal(calls.length,1);
});
