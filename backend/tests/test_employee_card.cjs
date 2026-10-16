const {test}=require('node:test'),assert=require('node:assert/strict');
const {employeeNextMovements}=require('../app/static/js/employee_card.js');
test('next events come from stored future movements without inferred dates',()=>{
 const items=[{id:3,transport_type:'SELF',movement_type:'DEPARTURE',event_datetime:'2026-10-08T12:00:00'},
 {id:2,transport_type:'SELF',movement_type:'ARRIVAL',event_datetime:'2026-10-07T12:00:00'},
 {id:1,movement_type:'ARRIVAL',event_datetime:'2026-10-05T12:00:00'}];
 const before=JSON.stringify(items),next=employeeNextMovements(items,'2026-10-06T00:00:00');
 assert.equal(next.ARRIVAL.id,2);assert.equal(next.DEPARTURE.id,3);assert.equal(JSON.stringify(items),before);
 assert.deepEqual(employeeNextMovements([],'2026-10-06T00:00:00'),{ARRIVAL:undefined,DEPARTURE:undefined});
});
test('forecast uses last actual movement and crosses month/year boundaries',()=>{
 const arrival={id:1,movement_type:'ARRIVAL',event_datetime:'2026-12-25T12:00:00'};
 const employee={max_shift_days:20,max_off_shift_days:10};
 assert.equal(employeeNextMovements([arrival],'2026-12-26T00:00:00',employee).DEPARTURE.event_datetime,'2027-01-14');
 const departure={id:2,movement_type:'DEPARTURE',event_datetime:'2026-12-26T12:00:00'};
 const next=employeeNextMovements([arrival,departure],'2026-12-27T00:00:00',employee);
 assert.equal(next.ARRIVAL.event_datetime,'2027-01-05');assert.equal(next.DEPARTURE,undefined);
 assert.equal(employeeNextMovements([arrival],'2026-12-26T00:00:00',{}).DEPARTURE,undefined);
});
test('confirmed ticket overrides forecast; unlinked RAIL cannot override it',()=>{
 const actual={id:1,movement_type:'ARRIVAL',event_datetime:'2026-10-01T12:00:00'};
 const rail={id:2,movement_type:'DEPARTURE',transport_type:'RAIL',event_datetime:'2026-10-12T12:00:00'};
 const employee={max_shift_days:20};
 assert.equal(employeeNextMovements([actual,rail],'2026-10-05T12:00:00',employee).DEPARTURE.event_datetime,'2026-10-21');
 assert.equal(employeeNextMovements([actual,{...rail,confirmed_ticket_id:4}],'2026-10-05T12:00:00',employee).DEPARTURE.id,2);
});
