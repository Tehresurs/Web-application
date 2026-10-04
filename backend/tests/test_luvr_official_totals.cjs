const {test}=require('node:test'),assert=require('node:assert/strict');
const {renderLuvrDayTotals}=require('../app/static/js/luvr_day_totals.js');
function element(){return {children:[],dataset:{},append(e){this.children.push(e);},replaceChildren(){this.children=[];}};}
test('official footer uses API equivalents and supplied employee totals only',()=>{
 global.document={createElement:element};const footer=element();
 const data={formed:true,day_totals:[{date:'2026-10-01',work_equivalent:1.5,full_count:999}],employees:[{totals:{work_days_total:1,travel_days_total:2,downtime_days_total:3}},{totals:{work_days_total:.5,travel_days_total:1,downtime_days_total:0}}]};
 const before=JSON.stringify(data);renderLuvrDayTotals(footer,data);
 assert.equal(footer.children.length,1);const cells=footer.children[0].children;
 assert.equal(cells[1].textContent,'Итого');assert.equal(cells[8].textContent,'1,5');
 assert.deepEqual(cells.slice(9).map(c=>c.textContent),['1,5','3','','3','']);
 assert.equal(JSON.stringify(data),before);assert.equal(footer.children[0].dataset.employee,undefined);
 renderLuvrDayTotals(footer,{formed:false});assert.equal(footer.children.length,0);
 delete global.document;
});
