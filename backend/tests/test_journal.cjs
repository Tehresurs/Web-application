const {test} = require('node:test');
const assert = require('node:assert/strict');
const {journalQuery, journalOptions, journalItemLabel, journalHistoryFilters} = require('../app/static/js/journal.js');

test('both views support all four filter combinations', () => {
    for (const view of ['object', 'employee']) {
        for (const [employee, object] of [['', ''], ['12', ''], ['', '34'], ['12', '34']]) {
            const query = new URLSearchParams(journalQuery('2026-09-01', '2026-09-30', view, employee, object));
            assert.equal(query.get('view'), view);
            assert.equal(query.get('employee_id'), employee || null);
            assert.equal(query.get('object_id'), object || null);
            assert.equal(query.get('date_from'), '2026-09-01');
        }
    }
});
test('invalid periods are rejected, single day accepted', () => {
    assert.throws(() => journalQuery('', '2026-09-30', 'object'));
    assert.throws(() => journalQuery('2026-10-01', '2026-09-30', 'object'));
    assert.ok(journalQuery('2026-09-24', '2026-09-24', 'employee'));
});
test('directory options deduplicate by ID rather than name', () => {
    const options = journalOptions([
        {id: 1, name: 'A'}, {id: 1, name: 'A'}, {id: 2, name: 'A'},
    ], 'id', 'name');
    assert.deepEqual(options, [['1','A'], ['2','A']]);
    assert.deepEqual(journalOptions([], 'id', 'name'), []);
});

test('typed IDs cannot collide and all omits every entity filter', () => {
    for (const view of ['object','employee']) {
        for (const employee of ['', '12']) {
            const parent=new URLSearchParams(journalQuery('2026-09-01','2026-09-30',view,employee,'object:15',false));
            assert.equal(parent.get('object_id'),'15');
            assert.equal(parent.get('include_subobjects'),'false');
            assert.equal(parent.get('subobject_id'),null);
            const child=new URLSearchParams(journalQuery('2026-09-01','2026-09-30',view,employee,'subobject:15'));
            assert.equal(child.get('subobject_id'),'15');
            assert.equal(child.get('object_id'),null);
            const all=new URLSearchParams(journalQuery('2026-09-01','2026-09-30',view));
            for (const key of ['employee_id','object_id','subobject_id']) assert.equal(all.get(key),null);
        }
    }
    for (const value of ['object:0','subobject:0','0','invalid']) {
        assert.throws(()=>journalQuery('2026-09-01','2026-09-30','object','',value));
    }
});

test('history navigation preserves period context and the other filter', () => {
    const current={employee:'',object:'subobject:15',includeSubobjects:false,view:'object',from:'2026-09-01',to:'2026-09-30'};
    const engineer=journalHistoryFilters(current,'employee',{employee_id:12});
    assert.deepEqual(engineer,{...current,employee:'12',view:'employee'});
    const position=journalHistoryFilters(engineer,'object',{control_item_key:'object:7'});
    assert.equal(position.employee,'12');
    assert.equal(position.object,'object:7');
    assert.equal(position.from,current.from);
    assert.equal(position.to,current.to);
    assert.match(journalItemLabel({control_item_type:'subobject',control_item_name:'Подъезд',object_name:'Куст'}),/ПОДОБЪЕКТ: Подъезд ↳ Куст/);
});
