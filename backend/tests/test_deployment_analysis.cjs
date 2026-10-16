const test=require('node:test'),assert=require('node:assert/strict');
const {staffingSeries,analysisNumber}=require('../app/static/js/deployment_analysis.js');
test('Position selector uses backend values without recalculating staffing',()=>{
 const history=[{staffing_total:{planned:4,actual:2},staffing:[{position_id:3,planned:1,actual:0}]},{staffing_total:{planned:4,actual:null},staffing:[{position_id:3,planned:1,actual:null}]}];
 assert.deepEqual(staffingSeries(history,'3').map(p=>p.actual),[0,null]);
 assert.deepEqual(staffingSeries(history,'total').map(p=>p.actual),[2,null]);
});
test('Zero and unknown metrics stay distinct',()=>{assert.equal(analysisNumber(null),'—');assert.equal(analysisNumber(0),'0');assert.equal(analysisNumber(1.5),'1,5');});
