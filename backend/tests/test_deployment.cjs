const test=require('node:test');
const assert=require('node:assert/strict');
const {deploymentTableRows}=require('../app/static/js/deployment.js');
test('Contract has exactly seven columns, missing values stay blank',()=>{
    assert.deepEqual(deploymentTableRows({rows:[{number:1,object_name:'Все объекты контроля',employee_name:'Employee',source:'PLAN'}]}),[[1,'Все объекты контроля','','Employee','','','']]);
});
