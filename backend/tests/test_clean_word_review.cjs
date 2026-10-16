const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {
  createCleanWordReviewClient,
  buildCleanWordConfirmation
}=require('../app/static/js/clean_word_review.js');

const parsedReport={
  report_date:'2026-10-14',
  report_date_raw:'14.10.2026',
  full_name:'Исходное Имя Инженера',
  employee_id:null,
  object_name:'Написание объекта из Word',
  entity_id:null,
  general_contractor:'Генподрядчик из Word',
  general_contractor_id:null,
  subcontractor:'—',
  business_data:{
    inspector:{full_name:{raw:'Исходное Имя Инженера'}},
    object:{raw:'Написание объекта из Word',value:'Написание объекта из Word'},
    general_contractor:{raw:'Генподрядчик из Word'},
    subcontractor:{raw:'—'},
    subcontractor_match:{status:'not_applicable'}
  }
};

test('parse, manual correction and confirmation stay on clean-start API',async()=>{
  const calls=[];
  const responses=[
    {item:{profile:'test',contract:'entity_id',schema:'public'}},
    {dictionaries:{
      entities:[{entity_id:42,name:'Объект',parent_entity_id:null}],
      employees:[{id:17,full_name:'Согласованный инженер'}],
      organizations:[{id:23,name:'Согласованный генподрядчик'}]
    }},
    {intermediate_report:parsedReport},
    {confirmed_report:{status:'confirmed_pending_save',persistence:{
      daily_facts_written:false,aliases_written:false,other_records_written:false
    }}}
  ];
  class FakeForm {
    append(name,value){this.fields={name,value};}
  }
  const client=createCleanWordReviewClient(async(url,options={})=>{
    calls.push({url,options});
    return {ok:true,json:async()=>responses.shift()};
  },()=>new FakeForm());

  await client.verify();
  const dictionaries=await client.dictionaries();
  assert.deepEqual(dictionaries.employees,[{id:17,full_name:'Согласованный инженер'}]);
  const report=await client.parse({name:'daily.docx'});
  const payload=buildCleanWordConfirmation(report,{
    reportDate:'2026-10-14',
    employeeId:'17',
    entityId:'42',
    generalContractorId:'23',
    subcontractorId:''
  },true);
  const result=await client.confirm(payload);
  assert.equal(result.confirmed_report.status,'confirmed_pending_save');
  assert.deepEqual(calls.map(call=>call.url),[
    '/api/clean-construction-entities/environment',
    '/api/clean-construction-entities/word-report/dictionaries',
    '/api/clean-construction-entities/word-report/parse',
    '/api/clean-construction-entities/word-report/confirm'
  ]);
  assert.equal(calls[2].options.body.fields.name,'file');
  assert.equal(calls[2].options.body.fields.value.name,'daily.docx');
  assert.deepEqual(JSON.parse(calls[3].options.body),{
    confirmed:true,
    report_date:'2026-10-14',
    source_full_name:'Исходное Имя Инженера',
    employee_id:17,
    source_object_name:'Написание объекта из Word',
    entity_id:42,
    source_general_contractor:'Генподрядчик из Word',
    general_contractor_id:23,
    source_subcontractor:'—',
    subcontractor_required:false,
    subcontractor_id:null
  });
  assert.ok(calls.every(call=>call.url.startsWith('/api/clean-construction-entities')));
  assert.ok(calls.every(call=>!call.url.includes('/aliases')));
  assert.ok(!/(object_id|subobject_id|daily_control_results)/.test(calls[3].options.body));
});

test('required selections and explicit review acknowledgement gate confirmation',()=>{
  assert.throws(()=>buildCleanWordConfirmation(parsedReport,{
    reportDate:'2026-10-14',employeeId:'17',entityId:'42',generalContractorId:'23'
  },false),/проверены/);
  assert.throws(()=>buildCleanWordConfirmation(parsedReport,{
    reportDate:'2026-10-14',employeeId:'',entityId:'42',generalContractorId:'23'
  },true),/Выберите сотрудника/);
  assert.throws(()=>buildCleanWordConfirmation(parsedReport,{
    reportDate:'',employeeId:'17',entityId:'42',generalContractorId:'23'
  },true),/корректную дату/);
  assert.throws(()=>buildCleanWordConfirmation(parsedReport,{
    reportDate:'2026-02-31',employeeId:'17',entityId:'42',generalContractorId:'23'
  },true),/корректную дату/);
});

test('clean review has a separate page and never loads legacy processing.js',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../app/templates/clean_word_review.html'),'utf8');
  const js=fs.readFileSync(path.join(__dirname,'../app/static/js/clean_word_review.js'),'utf8');
  assert.match(html,/clean_word_review\.js/);
  assert.doesNotMatch(html,/processing\.js/);
  assert.match(js,/Исходное название объекта/);
  assert.match(js,/ПОДТВЕРЖДЁН/);
});
