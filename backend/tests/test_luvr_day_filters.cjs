const test=require('node:test');
const assert=require('node:assert/strict');
const {luvrMatchesDayFilters}=require('../app/static/js/luvr_month.js');
test('day filters match final values, combine dates and preserve source records',()=>{
 const employee={days:[{date:'2026-10-05',final_display:'0,5',auto_display:'1'},{date:'2026-10-06',final_display:'МВ'}]};
 const before=JSON.stringify(employee);
 assert.ok(luvrMatchesDayFilters(employee,{}));
 assert.ok(luvrMatchesDayFilters(employee,{'2026-10-05':'0,5','2026-10-06':'МВ'}));
 assert.equal(luvrMatchesDayFilters(employee,{'2026-10-05':'1'}),false);
 assert.equal(luvrMatchesDayFilters(employee,{'2026-10-05':'0,5','2026-10-06':'Д'}),false);
 assert.ok(luvrMatchesDayFilters({days:[{date:'2026-10-05',final_display:''}]},{'2026-10-05':''}));
 assert.equal(JSON.stringify(employee),before);
});
test('working filter includes full and half days only',()=>{
 for(const value of ['1','0,5','МВ','Д','П','Уволен','']){
  assert.equal(luvrMatchesDayFilters({days:[{date:'2026-10-05',final_display:value}]},
   {'2026-10-05':'WORKING'}),['1','0,5'].includes(value));
 }
});
