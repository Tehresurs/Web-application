const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {employeeArchiveListUrl,employeeArchiveDate,changeEmployeeArchive}=require('../app/static/js/employee_archive.js');

test('normal list defaults to active, archive uses explicit filter',()=>{
    assert.equal(employeeArchiveListUrl(false),'/api/employees');
    assert.equal(employeeArchiveListUrl(true),'/api/employees?archived=true');
});
test('archive dates retain local calendar date',()=>{
    assert.equal(employeeArchiveDate(null),'—');
    assert.equal(employeeArchiveDate('2026-10-15'),'15.10.2026');
    assert.equal(employeeArchiveDate('2026-10-15T23:59:00'),'15.10.2026 23:59');
});
test('archive requires confirmation and only sends explicit POST',async()=>{
    const calls=[];let prompt;
    const result=await changeEmployeeArchive({id:17,full_name:'Иванов',is_archived:false},async(...args)=>calls.push(args),text=>{prompt=text;return true;});
    assert.ok(result);assert.match(prompt,/история и назначения сохранятся/);
    assert.deepEqual(calls,[['/api/employees/17/archive',{method:'POST'}]]);
});
test('restoring does not send dismissal_date clearing',async()=>{
    const calls=[];let prompt;
    await changeEmployeeArchive({id:17,full_name:'Иванов',is_archived:true,dismissal_date:'2026-10-15'},async(...args)=>calls.push(args),text=>{prompt=text;return true;});
    assert.deepEqual(calls,[['/api/employees/17/restore',{method:'POST'}]]);
    assert.match(prompt,/Дата увольнения останется/);
});
test('cancel archive or restore never calls API',async()=>{
    for(const is_archived of [false,true]){
        let calls=0;assert.equal(await changeEmployeeArchive({id:1,is_archived},async()=>calls++,()=>false),false);assert.equal(calls,0);
    }
});
test('archive failure does not report success',async()=>{
    await assert.rejects(changeEmployeeArchive({id:1},async()=>{throw new Error('Ошибка');},()=>true),/Ошибка/);
});

const source=fs.readFileSync(require.resolve('../app/static/js/processing.js'),'utf8');
function ui(archived=false){
    const requests=[],alerts=[],button={dataset:{id:'7'},disabled:false};let handler,refresh=0;
    const context=vm.createContext({employeeList:{addEventListener:(event,fn)=>handler=fn},employeeItems:[{id:7,full_name:'Сотрудник',is_archived:archived}],changeEmployeeArchive,confirm:()=>true,alert:m=>alerts.push(m),fetch:async(url,options)=>{requests.push({url,...options});return {ok:true,json:async()=>({status:'ok'})};},loadEmployees:async()=>refresh++});
    vm.runInContext(source.slice(source.indexOf('employeeList?.addEventListener("click"'),source.indexOf('addAssignmentButton?.addEventListener')),context);
    return {context,requests,alerts,button,click:()=>handler({target:{closest:selector=>selector==='.employee-archive-button'?button:null}}),refresh:()=>refresh};
}
test('real employee UI handler archives and never sends physical DELETE',async()=>{
    const state=ui();await state.click();assert.equal(state.requests.length,1);
    assert.equal(state.requests[0].url,'/api/employees/7/archive');assert.equal(state.requests[0].method,'POST');
    assert.equal(state.refresh(),1);assert.equal(state.button.disabled,false);assert.deepEqual(state.alerts,[]);
});
test('real archived employee UI handler restores by explicit POST',async()=>{
    const state=ui(true);await state.click();assert.equal(state.requests[0].url,'/api/employees/7/restore');assert.equal(state.requests[0].method,'POST');
});
test('real employee UI cancellation makes no request',async()=>{
    const state=ui();state.context.confirm=()=>false;await state.click();assert.equal(state.requests.length,0);assert.equal(state.refresh(),0);
});
test('real employee UI blocks repeated clicks during pending archive',async()=>{
    const state=ui();let finish,calls=0;
    state.context.fetch=()=>{calls++;return new Promise(resolve=>finish=resolve);};
    const first=state.click();await state.click();assert.equal(calls,1);
    finish({ok:true,json:async()=>({status:'ok'})});await first;assert.equal(state.button.disabled,false);
});
test('late active list response cannot replace selected archive list',async()=>{
    const pending=[];let renders=0;
    const context=vm.createContext({employeeListRequest:0,employeeItems:[],employeeArchiveFilter:{value:'active'},employeeArchiveListUrl,fetch:()=>new Promise(resolve=>pending.push(resolve)),renderEmployees:()=>renders++});
    vm.runInContext(source.slice(source.indexOf('async function loadEmployees()'),source.indexOf('async function loadCrews()')),context);
    const old=context.loadEmployees();context.employeeArchiveFilter.value='archived';const current=context.loadEmployees();
    pending[1]({ok:true,json:async()=>({items:[{id:2,is_archived:true}]})});await current;
    pending[0]({ok:true,json:async()=>({items:[{id:1,is_archived:false}]})});await old;
    assert.equal(context.employeeItems[0].id,2);assert.equal(renders,1);
});
