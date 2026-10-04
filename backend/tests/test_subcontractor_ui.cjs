const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {ReportSaveController} = require('../app/static/js/report_save.js');
const {journalQuery} = require('../app/static/js/journal.js');
const source = fs.readFileSync('app/static/js/processing.js', 'utf8');

class Element {
    constructor(tag) { Object.assign(this, {tag, children:[], style:{}, handlers:{}, disabled:false}); }
    append(...children) { this.children.push(...children); }
    setAttribute() {}
    addEventListener(name, fn) { this.handlers[name] = fn; }
}
const walk = node => [node, ...(node.children || []).flatMap(walk)];
const config = {kind:'subcontractor', parsedField:'subcontractor', idField:'subcontractor_id',
    statusField:'subcontractor_status', candidatesField:'subcontractor_candidates', resolvedField:'resolved_subcontractor', problemWords:['субподряд']};
function setup() {
    const calls = [], logs = [];
    const context = {console:{error(){}},window:{alert(){}}, document:{createElement:tag=>new Element(tag)},
        renderReports(){}, openDetails(){}, addProcessingLog:(...args)=>logs.push(args)};
    vm.createContext(context);
    for (const [start, end] of [
        ['function getFinalReportStatus(', 'function buildStatus('],
        ['function getCandidateEntity(', 'async function resolvePositionId('],
        ['async function addNewDatabaseItem(', 'function buildCheckRow('],
        ['function buildCheckRow(', 'function flattenAssignmentCategories('],
    ]) vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end)), context);
    context.apiPost = async (url, payload) => { calls.push({url,payload}); return {item:{id:27,name:payload.name}}; };
    return {context,calls,logs};
}
const report = () => ({subcontractor:'ООО Строй Мантаж',subcontractor_status:'similar',
    employee_status:'found',object_status:'found',general_contractor_status:'found',general_contractor_id:15,
    general_contractor:'ПО',problems:['Требуется согласование субподрядчика']});

test('selection resolves only subcontractor; remembered selection uses separate role and raw source', async()=>{
    const {context,calls,logs}=setup(); const item=report();
    await context.confirmAndRemember(item,config,{po:{id:27,name:'СтройМонтаж'}},false);
    assert.equal(item.general_contractor_id,15); assert.equal(item.subcontractor_id,27);
    assert.equal(item.subcontractor,'ООО Строй Мантаж'); assert.equal(item.problems.length,0);
    assert.equal(calls.length,0); assert.equal(context.getFinalReportStatus(item),'verified');
    await context.confirmAndRemember(item,config,{po:{id:27,name:'СтройМонтаж'}},true);
    assert.equal(calls[0].url,'/api/value-aliases');
    assert.equal(calls[0].payload.entity_type,'subcontractor');
    assert.equal(calls[0].payload.source_value,item.subcontractor);
    assert.ok(logs.some(x=>x[1].includes('SUBCONTRACTOR_SELECTED')));
});

test('new subcontractor uses organization API without alias or main PO change', async()=>{
    const {context,calls,logs}=setup(); const item=report(); item.subcontractor_status='new';
    await context.addNewDatabaseItem(item,config,new Element('button'),new Element('small'));
    assert.equal(calls.length,1); assert.equal(calls[0].url,'/api/po-types');
    assert.equal(item.subcontractor_id,27); assert.equal(item.general_contractor_id,15);
    assert.equal(item.subcontractor_status,'found'); assert.ok(item.resolved_subcontractor.added);
    assert.ok(logs.some(x=>x[1].includes('SUBCONTRACTOR_CREATED')));
});

test('absence is resolved and offers no creation, while similar/new block completion',()=>{
    const {context}=setup(); const item=report();
    for(const status of ['similar','new']) {
        item.subcontractor_status=status;
        assert.notEqual(context.getFinalReportStatus(item),'verified');
    }
    item.subcontractor=null; item.subcontractor_status='not_applicable'; item.problems=[];
    assert.equal(context.getFinalReportStatus(item),'verified');
    const nodes=walk(context.buildCheckRow(item,config));
    assert.ok(nodes.some(x=>x.textContent==='ОТСУТСТВУЕТ'));
    assert.equal(nodes.filter(x=>x.tag==='button').length,0);
});

test('alias conflict blocks save and does not overwrite mapping',async()=>{
    const {context,calls}=setup(); const item=report();
    context.apiPost=async(url,payload)=>{calls.push({url,payload});throw Object.assign(new Error('Конфликт'),{status:409});};
    await context.confirmAndRemember(item,config,{po:{id:27,name:'СтройМонтаж'}},true);
    assert.equal(calls.length,1); assert.match(item.alias_conflicts.subcontractor,/другое соответствие/);
    assert.equal(item.subcontractor_id,27); assert.equal(context.getFinalReportStatus(item),'needs_approval');
});

test('only main PO needs assignment; save payload carries both roles in one fact request',async()=>{
    const {context}=setup(); const item={...report(),subcontractor_id:27,subcontractor_status:'found',assignments:{15:{id:4},27:{id:9}}};
    const entries=await context.getReportAssignmentPoEntries(item);
    assert.equal(entries.length,1); assert.equal(entries[0].id,15);
    const body=ReportSaveController.prototype.payload(item);
    assert.equal(body.general_contractor_id,15); assert.equal(body.subcontractor_id,27);
    assert.deepEqual(body.assignments,{'15':4});
    item.subcontractor=null; item.subcontractor_status='not_applicable';
    assert.equal(ReportSaveController.prototype.payload(item).subcontractor_id,undefined);
});

test('journal subcontractor filter has no fake all ID and validates positive IDs',()=>{
    const args=['2026-09-01','2026-09-30','employee','1','subobject:3',true];
    const q=new URLSearchParams(journalQuery(...args,'27'));
    assert.equal(q.get('subcontractor_id'),'27'); assert.equal(q.get('subobject_id'),'3');
    assert.equal(new URLSearchParams(journalQuery(...args,'')).has('subcontractor_id'),false);
    assert.throws(()=>journalQuery(...args,'0'));
});
