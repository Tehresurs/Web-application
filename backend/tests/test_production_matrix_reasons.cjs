const test=require('node:test');
const assert=require('node:assert/strict');
const {pmCheckReasons}=require('../app/static/js/production_matrix.js');
test('check tooltip lists every cause and preserves unknown diagnostic codes',()=>{
 const text=pmCheckReasons({warnings:['LUVR_UNKNOWN','FACT_OUTSIDE_KNOWN_PERIOD','CUSTOM_REASON']});
 assert.equal(text.split('; ').length,3);
 assert.ok(!text.includes('LUVR_UNKNOWN'));
 assert.ok(!text.includes('FACT_OUTSIDE_KNOWN_PERIOD'));
 assert.ok(text.includes('CUSTOM_REASON'));
 assert.equal(pmCheckReasons({warnings:[]}), '');
});
