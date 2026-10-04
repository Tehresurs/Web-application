const {test}=require('node:test'),assert=require('node:assert/strict');
const {luvrExportPayload,luvrSpecialtyMissing,openLuvrEmployee}=require('../app/static/js/luvr_month.js');
test('export sends visible employee IDs in order, not visual numbers',()=>{
 const rows=[45,18,72,6].map(id=>({dataset:{employee:String(id)}}));
 assert.deepEqual(luvrExportPayload({year:2026,month:10},rows),{year:2026,month:10,employee_ids:[45,18,72,6]});
 rows.reverse();assert.deepEqual(luvrExportPayload({year:2026,month:10},rows).employee_ids,[6,72,18,45]);
});
test('specialty NULL empty and whitespace are missing',()=>{
 for(const specialty of [null,'','   ',undefined])assert.equal(luvrSpecialtyMissing({specialty}),true);
 assert.equal(luvrSpecialtyMissing({specialty:'ОС'}),false);
});
test('name opens existing employee editor by ID including archive',async()=>{
 const items=[{id:18,full_name:'Иванов'},{id:45,full_name:'Иванов',is_archived:true}];let opened;
 await openLuvrEmployee(45,async url=>{assert.equal(url,'/api/employees?include_archived=true');return {items};},item=>{opened=item;});
 assert.equal(opened,items[1]);
});
test('missing employee never opens wrong record',async()=>{
 let opened=false;await assert.rejects(()=>openLuvrEmployee(9,async()=>({items:[{id:1}]}),()=>opened=true),/Сотрудник не найден/);assert.equal(opened,false);
});
