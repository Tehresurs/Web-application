const {test}=require('node:test');
const assert=require('node:assert/strict');
const {luvrHistoryPayload,luvrLocalDate,luvrHistoryLabel,LuvrHistoryController,luvrHistoryRequest}=require('../app/static/js/luvr_history.js');

test('SELF movement sends local date/time, stations and explicit null source',()=>{
    const payload=luvrHistoryPayload('movements',{date:'2026-10-01',time:'07:59',movement_type:'ARRIVAL',departure_station:' А ',arrival_station:''});
    assert.deepEqual(payload,{movement_type:'ARRIVAL',transport_type:'SELF',event_datetime:'2026-10-01T07:59',departure_station:'А',arrival_station:null,source_file:null});
});
test('all time boundaries and microseconds retain the entered calendar day',()=>{
    for(const time of ['00:00','07:59','08:00','12:59','13:00','19:59','20:00','23:59:59.123456']){
        assert.equal(luvrHistoryPayload('movements',{date:'2026-09-30',time,movement_type:'DEPARTURE'}).event_datetime,`2026-09-30T${time}`);
    }
    assert.equal(luvrLocalDate('2026-09-30T23:59:59'),'30.09.2026');
});
test('movement requires both date and time',()=>{
    assert.throws(()=>luvrHistoryPayload('movements',{date:'2026-10-01'}));
    assert.throws(()=>luvrHistoryPayload('movements',{time:'08:00'}));
});
test('open sickness is separate from movements and can be closed',()=>{
    const open=luvrHistoryPayload('sick-periods',{date_from:'2026-10-01'});
    assert.deepEqual(open,{date_from:'2026-10-01',date_to:null,comment:null});
    assert.equal(luvrHistoryLabel('sick-periods',open),'Болеет с 01.10.2026');
    const closed=luvrHistoryPayload('sick-periods',{date_from:'2026-10-01',date_to:'2026-10-01',comment:' Выздоровел '});
    assert.equal(closed.comment,'Выздоровел');assert.ok(!('movement_type' in closed));
});
test('invalid period or missing required exception fields rejected',()=>{
    for(const kind of ['sick-periods','duration-exceptions']){
        assert.throws(()=>luvrHistoryPayload(kind,{date_from:'2026-10-02',date_to:'2026-10-01'}));
        assert.throws(()=>luvrHistoryPayload(kind,{}));
    }
    assert.throws(()=>luvrHistoryPayload('duration-exceptions',{date_from:'2026-10-01',comment:'yes'}));
    assert.throws(()=>luvrHistoryPayload('duration-exceptions',{date_from:'2026-10-01',date_to:'2026-10-02',comment:' \n '}));
});
test('both exception types retain dates and comment without generating events',()=>{
    for(const type of ['SHIFT','OFF_SHIFT']){
        assert.deepEqual(luvrHistoryPayload('duration-exceptions',{date_from:'2026-10-01',date_to:'2026-10-02',comment:' Отпуск ',exception_type:type}),{date_from:'2026-10-01',date_to:'2026-10-02',comment:'Отпуск',exception_type:type});
    }
});
test('movement labels retain RAIL origin and source without conversion',()=>{
    assert.equal(luvrHistoryLabel('movements',{event_datetime:'2026-10-01T00:01:00',movement_type:'ARRIVAL',transport_type:'RAIL',source_file:'ticket.pdf'}),'01.10.2026 00:01:00 · Заезд · ЖД · ticket.pdf');
});
function harness(request=async()=>({items:[]})){
    const renders=[],errors=[];
    const controller=new LuvrHistoryController(request,state=>renders.push({id:state.employeeId,items:state.items,busy:state.busy}),message=>errors.push(message));
    return {controller,renders,errors};
}
test('unsaved employee cannot load or mutate history',async()=>{
    let calls=0;const {controller}=harness(async()=>{calls++;return {items:[]};});controller.open(null);
    await controller.load();assert.equal(await controller.mutate('movements','POST',{}),false);assert.equal(calls,0);
});
test('history loads all sections scoped to selected employee',async()=>{
    const calls=[];const {controller}=harness(async url=>{calls.push(url);return {items:[{id:1}]};});controller.open(7);await controller.load();
    assert.equal(calls.length,3);assert.ok(calls.every(url=>url.startsWith('/api/employees/7/luvr/')));
    assert.equal(controller.items.movements[0].id,1);
});
test('explicit create, patch and delete use the correct scoped methods',async()=>{
    const calls=[];const {controller}=harness(async(...args)=>{calls.push(args);return {items:[]};});controller.open(17);
    const payload=luvrHistoryPayload('movements',{date:'2026-10-01',time:'08:00',movement_type:'ARRIVAL'});
    for(const [method,id] of [['POST',null],['PATCH',8],['DELETE',8]]){
        calls.length=0;assert.ok(await controller.mutate('movements',method,payload,id));
        assert.deepEqual(calls[0],[`/api/employees/17/luvr/movements${id?'/8':''}`,method,payload]);
        assert.equal(calls.length,4); // One explicit mutation, three read-only refreshes.
    }
});
test('double click sends only one mutation',async()=>{
    let resolve,calls=0;const {controller}=harness((url,method)=>{if(method){calls++;return new Promise(r=>resolve=r);}return Promise.resolve({items:[]});});
    controller.open(1);const first=controller.mutate('movements','POST',{});
    assert.equal(await controller.mutate('movements','POST',{}),false);resolve({});await first;assert.equal(calls,1);
});
test('late load for previous employee never changes new employee history',async()=>{
    const pending=[];const {controller}=harness(()=>new Promise(r=>pending.push(r)));
    controller.open(1);const load=controller.load();controller.open(2);
    pending.forEach(resolve=>resolve({items:[{employee_id:1}]}));await load;
    assert.equal(controller.employeeId,2);assert.deepEqual(controller.items,{});assert.equal(controller.busy,false);
});
test('late mutation for previous employee never refreshes the new one',async()=>{
    let resolve;const calls=[];const {controller}=harness((...args)=>{calls.push(args);return new Promise(r=>resolve=r);});
    controller.open(1);const save=controller.mutate('movements','POST',{});controller.open(2);resolve({});
    assert.equal(await save,false);assert.equal(calls.length,1);assert.deepEqual(controller.items,{});
});
test('failure keeps history and permits retry',async()=>{
    const {controller,errors}=harness(async()=>{throw new Error('Сохранение не выполнено');});controller.open(1);controller.items={movements:[{id:3}]};
    assert.equal(await controller.mutate('movements','DELETE',null,3),false);
    assert.equal(controller.items.movements.length,1);assert.equal(controller.busy,false);assert.equal(errors.length,1);
});
test('non-JSON server failure is shown as a readable message',async()=>{
    const previous=global.fetch;global.fetch=async()=>({ok:false,json:async()=>{throw new Error('Internal Server Error');}});
    try{await assert.rejects(luvrHistoryRequest('/test'),/Не удалось выполнить операцию/);}finally{global.fetch=previous;}
});
