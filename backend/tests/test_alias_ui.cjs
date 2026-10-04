const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/js/processing.js', 'utf8');

function setup(fail = false) {
    const calls = [], alerts = [];
    const context = {console:{error(){}},window: {alert: value => alerts.push(value)},
        confirmCandidate: (report, config, candidate) => { report[config.idField] = candidate.id; },
        getCandidateId: candidate => candidate.id,
        recalculateReportStatus(){}, renderReports(){},
        apiPost: async (url, payload) => {
            calls.push({url, payload});
            if (fail) throw Object.assign(new Error('Для этого значения уже сохранено другое соответствие.'), {status:409});
        }};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('async function confirmAndRemember('), source.indexOf('async function apiPost(')), context);
    return {context, calls, alerts};
}

for (const kind of ['employee', 'object', 'subobject', 'po', 'subcontractor']) {
    test(`${kind}: checkbox off uses selection only; on preserves raw source`, async () => {
        const {context, calls} = setup();
        const config = {kind, parsedField: 'raw', idField: 'target',statusField:kind+'_status'};
        const report = {raw: '  Исходная ОШИБКА  '};
        await context.confirmAndRemember(report, config, {id:17}, false);
        assert.equal(report.target, 17);
        assert.equal(calls.length, 0);
        await context.confirmAndRemember(report, config, {id:17}, true);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, '/api/value-aliases');
        assert.equal(calls[0].payload.entity_type, kind);
        assert.equal(calls[0].payload.source_value, report.raw);
        assert.equal(calls[0].payload.target_id, 17);
    });
}

test('conflict keeps current selection and reports failure without overwriting alias', async () => {
    const {context, calls, alerts} = setup(true);
    const report = {raw:'Ошибка'};
    await context.confirmAndRemember(report, {kind:'employee',parsedField:'raw',idField:'target',statusField:'employee_status'}, {id:18}, true);
    assert.equal(report.target, 18);
    assert.equal(calls.length, 1);
    assert.equal(alerts.length, 0);
    assert.match(report.alias_conflicts.employee, /другое соответствие/);
    assert.ok(report.alias_conflicts.employee);
});

test('new directory entry path never saves aliases', () => {
    const add = source.slice(source.indexOf('async function addNewDatabaseItem('), source.indexOf('function buildCheckRow('));
    assert.doesNotMatch(add, /value-aliases|confirmAndRemember/);
});

test('pending alias blocks readiness until save finishes', async () => {
    const {context}=setup();
    vm.runInContext(source.slice(source.indexOf('function getFinalReportStatus('),source.indexOf('function buildStatus(')),context);
    let finish;
    context.apiPost=()=>new Promise(resolve=>{finish=resolve;});
    const report={raw:'Ошибка',employee_status:'found',object_status:'found',general_contractor_status:'found'};
    const pending=context.confirmAndRemember(report,{kind:'employee',parsedField:'raw',idField:'target',statusField:'employee_status'},{id:17},true);
    assert.equal(context.getFinalReportStatus(report),'needs_approval');
    assert.equal(report.alias_pending.employee,true);
    finish({});
    await pending;
    assert.equal(context.getFinalReportStatus(report),'verified');
    assert.equal(Object.keys(report.alias_pending).length,0);
});

for (const status of [200, 201, 409, 404, 422, 500]) {
    test(`real apiPost handles HTTP ${status} without exposing technical response`, async () => {
        const {context, alerts} = setup();
        const requests = [], errors = [];
        const responseBody = status < 300 ? '{"status":"ok","created":true}' :
            status === 404 ? '{"detail":"Not Found"}' : 'Internal Server Error';
        context.console = {error: (...args) => errors.push(args)};
        context.fetch = async (url, options) => {
            requests.push({url, options});
            return {ok:status < 300,status,text:async()=>responseBody};
        };
        vm.runInContext(source.slice(source.indexOf('async function apiPost('), source.indexOf('async function resolvePositionId(')),context);
        const report = {raw:'Кецких Игорь Валерьевич'};
        // Capture the source before applying any selection, even if a caller mutates its display field.
        context.confirmCandidate = (item,config,candidate) => {item.target=candidate.id;item.raw='Кетских Игорь Валерьевич';};
        await context.confirmAndRemember(report,{kind:'employee',parsedField:'raw',idField:'target',statusField:'employee_status'},{id:17},true);
        assert.equal(report.target,17);
        assert.equal(requests.length,1);
        assert.equal(requests[0].url,'/api/value-aliases');
        assert.equal(requests[0].options.method,'POST');
        assert.deepEqual(JSON.parse(requests[0].options.body),{
            entity_type:'employee',source_value:'Кецких Игорь Валерьевич',target_id:17,
        });
        assert.equal(alerts.length,0);
        if(status < 300) {
            assert.equal(report.alias_messages.employee,'Выбор применён. Соответствие сохранено.');
            assert.equal(report.alias_conflicts.employee,undefined);
            assert.equal(errors.length,0);
        } else {
            assert.equal(report.alias_conflicts.employee,status===409
                ? 'Для этого значения уже сохранено другое соответствие.'
                : 'Выбор применён к текущему отчёту, но сохранить соответствие не удалось.');
            assert.equal(errors[0][1].status,status);
            assert.equal(errors[0][1].endpoint,'/api/value-aliases');
            assert.equal(errors[0][1].response_body,responseBody);
            assert.equal(errors[0][1].entity_type,'employee');
            assert.equal(errors[0][1].target_id,17);
        }
    });
}
