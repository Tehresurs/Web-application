const {test} = require('node:test');
const assert = require('node:assert/strict');
const {ReportSaveController} = require('../app/static/js/report_save.js');
const {attachReportSourcePaths} = require('../app/static/js/report_save.js');

test('legacy response receives captured source folder without losing resolutions', () => {
    const assignments = {3: {id: 4}};
    const items = [{filename: 'report.docx', employee_id: 12, assignments},
        {filename: 'other.docx', source_path: 'D:/original/other.docx'}];
    attachReportSourcePaths(items, 'C:\\reports\\');
    assert.equal(items[0].source_path, 'C:\\reports/report.docx');
    assert.equal(items[0].employee_id, 12);
    assert.equal(items[0].assignments, assignments);
    assert.equal(items[1].source_path, 'D:/original/other.docx');
    attachReportSourcePaths(items, 'D:/later-selection');
    assert.equal(items[0].source_path, 'C:\\reports/report.docx');
});

test('source fallback rejects filenames containing paths', () => {
    const items = [{filename: '../report.docx'}, {filename: 'C:\\other.docx'}, {}];
    attachReportSourcePaths(items, 'C:/reports');
    assert.ok(items.every(item => !item.source_path));
});

function element() {
    return {disabled: true, hidden: false, textContent: '', addEventListener() {}};
}
function report(name = 'first') {
    return {
        source_path: `C:/reports/${name}.docx`, report_date: '24.09.2026',
        employee_id: 1, object_id: 2, general_contractor_id: 3,
        employee_status: 'found', object_status: 'found', general_contractor_status: 'found',
        assignments: {3: {id: 4}}, localReady: true,
    };
}
function response(body, ok = true) { return {ok, json: async () => body}; }
function deferred() {
    let resolve;
    const promise = new Promise(done => {resolve = done;});
    return {promise, resolve};
}
function setup(fetchRequest) {
    const controller = new ReportSaveController({
        button: element(), retryButton: element(), message: element(), fetchRequest,
        ready: report => report.localReady, onState() {},
    });
    return controller;
}

test('archive warning stays visible without blocking an otherwise valid historical report',async()=>{
    const warning='Объект находится в архиве';
    const controller=setup(async path=>response(path.endsWith('/check')
        ?{can_save:true,saved:false,warnings:[warning]}
        :{saved:true,created:true,results:[{id:1}],warnings:[warning]}));
    controller.bind(report());await controller.refresh();
    assert.equal(controller.button.disabled,false);
    assert.ok(controller.message.textContent.includes(warning));
    await controller.save();assert.equal(controller.report.control_saved,true);
    assert.ok(controller.message.textContent.includes(warning));
});

test('archive warning does not override other blocking report problems',async()=>{
    const controller=setup(async()=>response({can_save:false,saved:false,problems:['Не выбрано ПО'],warnings:['Объект в архиве']}));
    controller.bind(report());await controller.refresh();
    assert.equal(controller.button.disabled,true);
    assert.ok(controller.message.textContent.includes('Не выбрано ПО'));
    assert.ok(controller.message.textContent.includes('Объект в архиве'));
});

test('duplicate result is shown plainly and cannot be saved again', async () => {
    let saves=0;
    const controller=setup(async path=>{
        if (path.endsWith('/check')) return response({can_save:true,saved:false});
        saves++;
        return response({saved:true,created:false,results:[{id:7,created:false}]});
    });
    controller.bind(report());
    await controller.refresh();
    await controller.save();
    await controller.save();
    assert.equal(saves,1);
    assert.equal(controller.message.textContent,'Этот результат уже сохранён.');
    assert.equal(controller.button.disabled,true);
});

test('readiness does not save; button needs server and local approval', async () => {
    const calls = [];
    const controller = setup(async path => {
        calls.push(path);
        return response({can_save: true, saved: false});
    });
    const item = report();
    item.localReady = false;
    controller.bind(item);
    assert.equal(controller.button.disabled, true);
    await controller.refresh();
    assert.equal(controller.button.disabled, true);
    item.localReady = true;
    await controller.refresh();
    assert.equal(controller.button.disabled, false);
    assert.ok(calls.every(path => path.endsWith('/check')));
});

test('server remarks disable save even when locally complete', async () => {
    const controller = setup(async () => response({can_save: false, saved: false, problems: ['Назначение удалено']}));
    controller.bind(report());
    await controller.refresh();
    assert.equal(controller.button.disabled, true);
    assert.match(controller.message.textContent, /Назначение удалено/);
});

test('double click sends one save and remembers success', async () => {
    const pending = deferred();
    let saves = 0;
    let body;
    const controller = setup(async (path, options) => {
        if (path.endsWith('/check')) return response({can_save: true, saved: false});
        saves++;
        body = JSON.parse(options.body);
        return pending.promise;
    });
    const item = report();
    controller.bind(item);
    await controller.refresh();
    const saving = controller.save();
    await controller.save();
    assert.equal(saves, 1);
    assert.equal(controller.button.disabled, true);
    assert.equal(body.path, item.source_path);
    assert.deepEqual(body.assignments, {'3': 4});
    assert.equal(body.report_date, undefined);
    pending.resolve(response({saved: true, results: [{id: 7}]}));
    await saving;
    assert.equal(item.control_saved, true);
    assert.equal(controller.button.textContent, '✓ Результат сохранён');
    assert.equal(controller.button.disabled, true);
});

test('reopened saved source is disabled even with unresolved local fields', async () => {
    const controller = setup(async () => response({can_save: false, saved: true}));
    const item = report();
    item.localReady = false;
    controller.bind(item);
    await controller.refresh();
    assert.equal(controller.button.textContent, '✓ Результат сохранён');
    assert.equal(controller.button.disabled, true);
});

test('late response for previous report cannot enable current report', async () => {
    const pending = deferred();
    const controller = setup(() => pending.promise);
    controller.bind(report());
    const checking = controller.refresh();
    controller.bind(report('second'));
    pending.resolve(response({can_save: true, saved: false}));
    await checking;
    assert.equal(controller.button.disabled, true);
});

test('changing assignment invalidates in-flight readiness', async () => {
    const pending = deferred();
    const controller = setup(() => pending.promise);
    const item = report();
    controller.bind(item);
    const checking = controller.refresh();
    item.assignments[3].id = 55;
    pending.resolve(response({can_save: true, saved: false}));
    await checking;
    assert.equal(controller.button.disabled, true);
});

test('network failure requires readiness recheck and allows recovery', async () => {
    let fail = true;
    const controller = setup(async path => {
        if (path.endsWith('/check')) return response({can_save: true, saved: false});
        if (fail) throw new Error('Network unavailable');
        return response({saved: true});
    });
    controller.bind(report());
    await controller.refresh();
    await controller.save();
    assert.equal(controller.button.disabled, true);
    assert.match(controller.message.textContent, /Проверить готовность/);
    fail = false;
    await controller.refresh();
    await controller.save();
    assert.equal(controller.report.control_saved, true);
});

test('saving previous report does not alter newly opened report', async () => {
    const pending = deferred();
    const controller = setup(path => path.endsWith('/check')
        ? Promise.resolve(response({can_save: true, saved: false})) : pending.promise);
    const first = report();
    controller.bind(first);
    await controller.refresh();
    const saving = controller.save();
    controller.close();
    const second = report('second');
    controller.bind(second);
    pending.resolve(response({saved: true}));
    await saving;
    assert.equal(first.control_saved, true);
    assert.equal(second.control_saved, undefined);
    assert.equal(controller.button.disabled, true);
    assert.equal(controller.button.textContent, 'Сохранить результат');
});
const {BatchReportSaveController} = require('../app/static/js/report_save.js');
function batch(reports, fetchRequest) {
    return new BatchReportSaveController({button: element(), retryButton: element(), message: element(),
        fetchRequest, ready: r => r.localReady, onState() {}, getReports: () => reports});
}
test('batch checks all reports and blocks on one unresolved report', async () => {
    const items = [report('a'), report('b')];
    items[1].localReady = false;
    let writes = 0;
    const c = batch(items, async path => {
        if (!path.endsWith('/check')) writes++;
        return response({can_save: true, saved: false});
    });
    await c.refresh();
    await c.save();
    assert.equal(c.button.disabled, true);
    assert.equal(writes, 0);
});
test('batch saves all reports and blocks repeated click', async () => {
    const items = [report('a'), report('b')];
    const writes = [];
    const c = batch(items, async (path, options) => {
        if (path.endsWith('/check')) return response({can_save: true, saved: false});
        writes.push(JSON.parse(options.body).path);
        return response({saved: true});
    });
    await c.refresh();
    assert.equal(c.button.disabled, false);
    await Promise.all([c.save(), c.save()]);
    assert.deepEqual(writes, items.map(r => r.source_path));
    assert.equal(c.button.textContent, '✓ Результат сохранён');
    assert.equal(c.button.disabled, true);
});
test('batch retries only remaining reports after partial failure', async () => {
    const items = [report('a'), report('b')];
    let fail = true;
    const writes = [];
    const c = batch(items, async (path, options) => {
        if (path.endsWith('/check')) return response({can_save: true, saved: false});
        const source = JSON.parse(options.body).path;
        writes.push(source);
        if (source === items[1].source_path && fail) throw new Error('Network error');
        return response({saved: true});
    });
    await c.refresh();
    await c.save();
    assert.equal(items[0].control_saved, true);
    assert.notEqual(items[1].control_saved, true);
    fail = false;
    await c.refresh();
    await c.save();
    assert.equal(writes.filter(path => path === items[0].source_path).length, 1);
    assert.ok(items.every(r => r.control_saved));
});
test('cleared batch ignores pending readiness response', async () => {
    const items = [report()];
    const pending = deferred();
    const c = batch(items, () => pending.promise);
    const checking = c.refresh();
    items.length = 0;
    c.sync();
    pending.resolve(response({can_save: true, saved: false}));
    await checking;
    clearTimeout(c.timer);
    await c.refresh();
    assert.equal(c.button.disabled, true);
});
