const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {ReportSaveController} = require('../app/static/js/report_save.js');
const source = fs.readFileSync('app/static/js/processing.js','utf8');

class Element {
    constructor(tag) { this.tag=tag; this.children=[]; this.style={}; this.handlers={}; this.value=''; this.disabled=false; }
    append(...items) { this.children.push(...items); }
    add(item) { this.append(item); }
    replaceChildren(...items) { this.children=items; }
    setAttribute() {}
    addEventListener(name, fn) { this.handlers[name]=fn; }
    remove() { this.removed=true; }
    get options() { return this.children; }
}
function setup() {
    const calls=[];
    const context={console,ConstructionChoices:require('../app/static/js/construction_choices.js'),window:{alert(){}}, document:{createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})},activeReportIndex:0,
        Option:function(text,value){this.textContent=text;this.value=value;},
        getFinalReportStatus:()=> 'verified',renderReports(){},openDetails(){},addProcessingLog(){},
        fetch:async()=>({ok:true,json:async()=>({items:[{id:5,name:'Родитель №55'},{id:6,name:'Другой'}]})})};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('function getCandidateEntity('),source.indexOf('async function resolvePositionId(')),context);
    vm.runInContext(source.slice(source.indexOf('async function addNewDatabaseItem('),source.indexOf('function buildCheckRow(')),context);
    vm.runInContext(source.slice(source.indexOf('function buildCheckRow('),source.indexOf('async function getReportAssignmentPoEntries(')),context);
    context.apiPost=async(url,payload)=>{
        calls.push({url,payload});
        return {item:{id:12,object_id:payload.object_id,name:payload.name,object_name:'Родитель №55'},object:{id:8,name:payload.name}};
    };
    return {context,calls};
}
const config={kind:'object',parsedField:'object_name',idField:'object_id',statusField:'object_status',resolvedField:'resolved_object',problemWords:['объект']};
const child={entity_kind:'subobject',subobject:{id:12,name:'Подъезд'},subobject_id:12,subobject_name:'Подъезд',object_id:5,object_name:'Родитель №55'};

test('selecting child keeps parent, then selecting object clears child',()=>{
    const {context}=setup();
    const report={object_name:'Исходное',problems:[]};
    context.confirmCandidate(report,config,child);
    assert.equal(report.object_id,5); assert.equal(report.subobject_id,12);
    assert.equal(report.resolved_object.name,'Родитель №55');
    assert.equal(report.resolved_subobject.name,'Подъезд');
    context.confirmCandidate(report,config,{entity_kind:'object',object:{id:6,name:'Другой'}});
    assert.equal(report.object_id,6); assert.equal(report.subobject_id,null);
    assert.equal(report.object_name,'Исходное');
});

test('remember child uses subobject alias, parent selection uses object alias',async()=>{
    const {context,calls}=setup();
    const report={object_name:'Исходное',problems:[]};
    await context.confirmAndRemember(report,config,child,true);
    assert.equal(calls[0].payload.entity_type,'subobject'); assert.equal(calls[0].payload.target_id,12);
    await context.confirmAndRemember(report,config,{object:{id:5,name:'Родитель'}},true);
    assert.equal(calls[1].payload.entity_type,'object'); assert.equal(calls[1].payload.target_id,5);
    assert.equal(calls[1].payload.source_value,'Исходное');
});

test('new parent clears previous subobject and creates no alias',async()=>{
    const {context,calls}=setup();
    const report={object_name:'Новый',subobject_id:12,resolved_subobject:{id:12},problems:[]};
    await context.addNewDatabaseItem(report,config,new Element('button'),new Element('small'));
    assert.equal(report.object_id,8); assert.equal(report.subobject_id,null);
    assert.equal(calls.length,1); assert.equal(calls[0].url,'/api/objects');
});

test('creation form loads parents, filters, requires parent and saves edited child',async()=>{
    const {context,calls}=setup();
    const report={object_name:'Подъезд из Word',problems:[]};
    const editor=context.buildSubobjectEditor(report,config);
    await editor.children[0].handlers.click();
    const form=editor.children[1];
    const [,nameLabel,search,parentLabel,save]=form.children;
    const name=nameLabel.children[0],parent=parentLabel.children[0];
    assert.equal(name.value,'Подъезд из Word');
    assert.equal(parent.options.length,3);
    await form.handlers.submit({preventDefault(){}});
    assert.equal(calls.length,0);
    search.value='55'; search.handlers.input(); assert.equal(parent.options.length,2);
    parent.value='5'; name.value='Подъезд уточнённый';
    await form.handlers.submit({preventDefault(){}});
    assert.equal(calls[0].url,'/api/subobjects');
    assert.equal(calls[0].payload.object_id,5);
    assert.equal(calls[0].payload.name,'Подъезд уточнённый');
    assert.equal(report.object_id,5); assert.equal(report.subobject_id,12);
    assert.equal(report.object_name,'Подъезд из Word');
});

test('save payload sends child or explicit null while assignments stay on parent',()=>{
    const payload=ReportSaveController.prototype.payload({source_path:'x.docx',object_status:'found',object_id:5,subobject_id:12,
        general_contractor_status:'found',general_contractor_id:3,assignments:{3:{id:9}}});
    assert.equal(payload.object_id,5); assert.equal(payload.subobject_id,12); assert.equal(payload.assignments[3],9);
    assert.equal(ReportSaveController.prototype.payload({}).subobject_id,null);
});

test('Word parent dropdown excludes children and archive and posts the promoted parent identity',async()=>{
    const {context,calls}=setup();
    context.fetch=async()=>({ok:true,json:async()=>({items:[
        {id:null,entity_id:20,name:'Самостоятельный',current_hierarchy:{entity_id:20,parent_entity_id:null}},
        {id:8,entity_id:21,name:'Дочерний',current_hierarchy:{entity_id:21,parent_entity_id:20}},
        {id:9,entity_id:22,name:'Архивный',is_archived:true,current_hierarchy:{entity_id:22,parent_entity_id:null}},
    ]})});
    context.apiPost=async(url,payload)=>{
        calls.push({url,payload});return {item:{id:30,entity_id:23,object_id:null,name:payload.name,
            current_hierarchy:{entity_id:23,name:payload.name,parent_entity_id:20,parent:{name:'Самостоятельный'}}}};
    };
    const report={object_name:'Новый',problems:[]};
    const editor=context.buildSubobjectEditor(report,config);
    await editor.children[0].handlers.click();
    const form=editor.children[1],parent=form.children[3].children[0];
    assert.deepEqual(parent.options.map(o=>o.value),['','entity:20']);
    parent.value='entity:20';await form.handlers.submit({preventDefault(){}});
    assert.equal(calls[0].payload.parent_entity_id,20);
    assert.equal(calls[0].payload.object_id,undefined);
    assert.equal(report.entity_id,23);
    assert.equal(report.object_id,null);
    assert.equal(report.resolved_object.name,'Самостоятельный');
    assert.equal(report.resolved_subobject.name,'Новый');
});

function descendants(node) { return [node,...(node.children || []).flatMap(descendants)]; }

test('subobject creation is offered only for unresolved objects; resolved child shows both names',()=>{
    const {context}=setup();
    for (const kind of ['object','employee','po']) {
        const row=context.buildCheckRow({object_status:'new',object_name:'Исходное'}, {...config,kind});
        assert.equal(descendants(row).some(n=>n.textContent==='Добавить как подобъект'),kind==='object');
    }
    for (const source of ['subobject_exact','subobject_alias']) {
        const report={object_status:'found',object_name:'Исходное',subobject_id:12,object_match_source:source,
            resolved_object:{id:5,name:'Родитель'},resolved_subobject:{id:12,name:'Подъезд'}};
        const nodes=descendants(context.buildCheckRow(report,config));
        assert.ok(nodes.some(n=>n.textContent==='Родительский объект (справочно): Родитель'));
        assert.ok(nodes.some(n=>n.textContent==='Объект / Подобъект: Подъезд'));
        assert.ok(nodes.some(n=>n.textContent===(source==='subobject_exact'?'ПОДОБЪЕКТ НАЙДЕН':'ИЗВЕСТНОЕ СООТВЕТСТВИЕ ПОДОБЪЕКТА')));
        assert.equal(nodes.filter(n=>n.tag==='button').length,0);
    }
});
