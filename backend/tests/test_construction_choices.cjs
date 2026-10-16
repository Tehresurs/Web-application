const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const choices = require('../app/static/js/construction_choices.js');
const {RailTicketController} = require('../app/static/js/rail_tickets.js');
const {createSubobjectDirectoryEditor} = require('../app/static/js/object_hierarchy.js');
const {ReportSaveController} = require('../app/static/js/report_save.js');
const {journalQuery} = require('../app/static/js/journal.js');
const source = fs.readFileSync('app/static/js/processing.js', 'utf8');
function entity(id, name, parent = null, legacyObject = id, legacyChild = null, archived = false) {
    const h = {entity_id: id, name, parent_entity_id: parent?.entity_id ?? null, parent,
        legacy_object_id: legacyObject, legacy_subobject_id: legacyChild, is_archived: archived, is_active: true};
    return {id: parent ? legacyChild : legacyObject, name, entity_id: id, current_hierarchy: h, is_archived: archived};
}
const root = entity(101, 'А', null, 1);
const promoted = entity(102, 'Б', null, null, 7);
const converted = entity(103, 'В', root.current_hierarchy, 3);
const archived = entity(104, 'Г', null, 4, null, true);
class Element {
    constructor() { Object.assign(this, {children: [], handlers: {}, value: '', hidden: false, disabled: false}); }
    append(...nodes) { this.children.push(...nodes); }
    add(node) { this.append(node); }
    replaceChildren(...nodes) { this.children = nodes; }
    get options() { return this.children; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    focus() {}
    set innerHTML(value) { this.replaceChildren(); this.html = value; }
}
global.Option = function(text, value) { this.textContent = text; this.value = String(value); };

test('parent choices contain only active roots, excluding self and converted objects', () => {
    assert.deepEqual(choices.parents([root, promoted, converted, archived], root).map(choices.value), ['entity:102']);
    assert.equal(choices.label(converted), 'А → В');
    const restored = entity(103, 'В', null, 3);
    assert.deepEqual(choices.parents([root, restored]).map(choices.value), ['entity:101', 'entity:103']);
});
test('identity payload never borrows an ID from another table; legacy values still work', () => {
    assert.deepEqual(choices.reference(choices.value(promoted)), {entity_id: 102});
    assert.deepEqual(choices.reference(choices.value(promoted), true), {parent_entity_id: 102});
    assert.deepEqual(choices.reference('7'), {object_id: 7});
    assert.deepEqual(choices.reference(''), {object_id: null});
    assert.throws(() => choices.reference('entity:null'));
    assert.equal(choices.selectedValue([root], {id: 777, object_id: null}), '');
});
test('historical selections resolve to the current entity and keep archived choices visible', () => {
    const select = new Element();
    choices.fill(select, [root, converted, archived], {id: 50, object_id: 3, object_name: 'В'});
    assert.equal(select.value, 'entity:103');
    assert.equal(select.options.find(o => o.value === select.value).textContent, 'А → В');
    choices.fill(select, [root, archived], {entity_id: 104, current_hierarchy: archived.current_hierarchy});
    assert.equal(select.value, 'entity:104');
    assert.match(select.options.find(o => o.value === select.value).textContent, /архив/);
    assert.equal(choices.options([root, archived]).rows.length, 1);
});
test('children of archived parents cannot be newly selected; history still appears', () => {
    const child = entity(105, 'Д', archived.current_hierarchy, null, 8);
    assert.equal(choices.options([child]).rows.length, 0);
    assert.equal(choices.options([child], child).rows[0].historical, true);
});
test('catalog fetch adds current children only in identity mode, without conversion endpoints', async () => {
    const calls = [];
    const request = async url => { calls.push(url); return {items: [converted]}; };
    assert.deepEqual(await choices.load(request, [{id: 1, name: 'А'}]), [{id: 1, name: 'А'}]);
    assert.equal(calls.length, 0);
    const items = await choices.load(request, [root, promoted]);
    assert.deepEqual(items.map(choices.value), ['entity:101', 'entity:102', 'entity:103']);
    assert.deepEqual(calls, ['/api/subobjects?include_inactive=true']);
});
test('ticket selection submits entity_id and clearing preserves the old API contract', async () => {
    const calls = [];
    const controller = new RailTicketController(async (url, options) => {
        calls.push(JSON.parse(options.body)); return {item: {id: 9}};
    }, () => {}, error => { throw new Error(error); });
    await controller.action(9, 'object', 'entity:102');
    await controller.action(9, 'object', '');
    assert.deepEqual(calls, [{entity_id: 102}, {object_id: null}]);
});
test('employee assignment editor loads current children and retains its historical selection', async () => {
    const context = {ConstructionChoices: choices, Option: global.Option, alert: error => {throw new Error(error);},
        assignmentObjectSelect: new Element(), assignmentPoSelect: new Element(), assignmentCategorySelect: new Element(),
        assignmentSaveButton: new Element(), assignmentError: new Element(), assignmentEditor: new Element(),
        fetch: async url => ({ok: true, json: async () => ({items: url.startsWith('/api/objects') ? [root, promoted]
            : url.startsWith('/api/subobjects') ? [converted, archived] : []})})};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('let assignmentObjectChoices'), source.indexOf('function closeAssignmentEditor')), context);
    await context.openAssignmentEditor({id: 50, object_id: 3, object_name: 'В', po_id: 1, category_id: 1});
    assert.equal(context.assignmentObjectSelect.value, 'entity:103');
    assert.equal(context.assignmentObjectSelect.options.filter(o => o.value === 'entity:103').length, 1);
    assert.ok(context.assignmentObjectSelect.options.some(o => o.value === 'entity:102'));
    assert.ok(!context.assignmentObjectSelect.options.some(o => o.value === 'entity:104'));
});
test('new child under a promoted root uses parent_entity_id; legacy move is not enabled for it', async () => {
    const ids = {}, calls = [];
    const doc = {getElementById: id => ids[id] ||= new Element(), createElement: () => new Element()};
    const editor = createSubobjectDirectoryEditor({document: doc, getObjects: () => [root, promoted, converted, archived],
        onSaved: async () => {}, request: async (url, options) => {
            calls.push([url, JSON.parse(options.body)]); return {ok: true, json: async () => ({item: {id: 8}})};
        }});
    editor.open(promoted);
    ids.subobjectDirectoryName.value = 'Новый';
    await ids.subobjectDirectoryForm.handlers.submit();
    assert.deepEqual(calls, [['/api/subobjects', {parent_entity_id: 102, name: 'Новый'}]]);
    assert.deepEqual(ids.subobjectDirectoryParent.options.map(o => o.value), ['entity:101', 'entity:102']);
    editor.open(root, {...entity(110, 'Ребёнок', root.current_hierarchy, null, 10), id: 10, object_id: 1});
    ids.subobjectDirectoryParent.value = 'entity:102';
    await ids.subobjectDirectoryForm.handlers.submit();
    assert.equal(calls.length, 1);
    assert.match(ids.subobjectDirectoryError.textContent, /API переноса/);
    editor.open(null, {...entity(111, 'Новый ребёнок', promoted.current_hierarchy, null, 11), object_id: null});
    assert.equal(ids.subobjectDirectoryParent.value, 'entity:102');
});
test('assignment save sends the chosen identity without a legacy placeholder', async () => {
    let save, payload;
    const context = {ConstructionChoices: choices, employeeEditId: 7, assignmentEditId: null,
        assignmentObjectSelect: {value: 'entity:102'}, assignmentPoSelect: {value: '1'}, assignmentCategorySelect: {value: '2'},
        assignmentSaveButton: {addEventListener: (_, fn) => {save = fn;}}, assignmentError: {},
        closeAssignmentEditor() {}, async loadEmployeeAssignments() {},
        fetch: async (url, options) => {payload=JSON.parse(options.body);return {ok: true,json:async()=>({})};}};
    vm.createContext(context);
    const line=source.split('\n').find(line=>line.startsWith('assignmentSaveButton?.addEventListener'));
    vm.runInContext(line,context);
    await save();
    assert.deepEqual(payload,{entity_id:102,po_id:1,category_id:2});
});
test('journal identity filter does not masquerade as object_id', () => {
    const query = new URLSearchParams(journalQuery('2026-10-01', '2026-10-14', 'object', '', 'entity:103'));
    assert.equal(query.get('entity_id'), '103');
    assert.equal(query.has('object_id'), false);
});
test('report payload preserves entity-only choice without fabricated legacy IDs', () => {
    const payload = ReportSaveController.prototype.payload({source_path: 'report.docx', object_status: 'found', entity_id: 103});
    assert.equal(payload.entity_id, 103);
    assert.equal(payload.object_id, undefined);
    assert.equal(payload.subobject_id, null);
});
test('editing a converted child with null id addresses its stable entity', async () => {
    const ids = {}, calls = [];
    const doc = {getElementById: id => ids[id] ||= new Element(), createElement: () => new Element()};
    const child = {...entity(103, 'Converted', root.current_hierarchy, 3, null), id: null};
    const editor = createSubobjectDirectoryEditor({document: doc, getObjects: () => [root],
        onSaved: async () => {}, request: async (url, options) => {
            calls.push([url, JSON.parse(options.body)]);
            return {ok: true, json: async () => ({item: child})};
        }});
    editor.open(null, child);
    ids.subobjectDirectoryName.value = 'Renamed';
    await ids.subobjectDirectoryForm.handlers.submit();
    assert.equal(calls[0][0], '/api/subobjects/103?id_type=entity');
    assert.equal(calls[0][1].name, 'Renamed');
    assert.equal(child.id, null);
});
