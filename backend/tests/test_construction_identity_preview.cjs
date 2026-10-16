const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {constructionIdentityEligibility, createConstructionIdentityPreview} =
    require('../app/static/js/construction_identity_preview.js');

class Element {
    constructor() {
        Object.assign(this, {children: [], handlers: {}, value: '', hidden: false, disabled: false, className: ''});
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    querySelectorAll() { return []; }
}

function catalog() {
    return [
        {entity_id: 1, name: 'Объект А', parent_entity_id: null, is_archived: false},
        {entity_id: 2, name: 'Объект Б', parent_entity_id: null, is_archived: false},
        {entity_id: 3, name: 'Подобъект В', parent_entity_id: 1, is_archived: false},
    ];
}

test('precheck accepts a valid root-to-child and child-to-root move', () => {
    const entities = catalog();
    assert.deepEqual(constructionIdentityEligibility(entities, 2, 1), {
        allowed: true, reason: 'Предварительная проверка пройдена. Преобразование не выполнено.',
    });
    assert.equal(constructionIdentityEligibility(entities, 3, null).allowed, true);
});

test('precheck rejects children as parents, entities with children, and duplicate names', () => {
    const entities = catalog();
    assert.equal(constructionIdentityEligibility(entities, 1, 3).allowed, false);
    assert.match(constructionIdentityEligibility(entities, 1, 2).reason, /есть подобъекты/);
    assert.match(constructionIdentityEligibility([...entities, {
        entity_id: 4, name: 'подобъект в', parent_entity_id: null, is_archived: false,
    }], 3, null).reason, /таким названием/);
});

test('precheck rejects archived parents and already-independent entities', () => {
    const entities = [...catalog(), {
        entity_id: 4, name: 'Архив', parent_entity_id: null, is_archived: true,
    }];
    assert.match(constructionIdentityEligibility(entities, 2, 4).reason, /вне архива/);
    assert.match(constructionIdentityEligibility(entities, 2, null).reason, /уже является самостоятельным/);
});

test('precheck evaluates the proposed name while preserving the original by default', () => {
    const entities = catalog();
    assert.equal(constructionIdentityEligibility(entities, 2, 1, 'Новое имя').allowed, true);
    assert.match(constructionIdentityEligibility(entities, 2, 1, 'Подобъект В').reason, /таким названием/);
    assert.equal(constructionIdentityEligibility(entities, 2, 1).allowed, true);
});

function previewController(entities = catalog(), overrides = {}) {
    const elements = new Map();
    const document = {
        getElementById: id => {
            if (!elements.has(id)) elements.set(id, new Element());
            return elements.get(id);
        },
        createElement: () => new Element(),
    };
    const calls = [];
    const controller = createConstructionIdentityPreview({
        document,
        getKnownEntities: () => entities,
        request: async (url, options) => {
            calls.push({url, options});
            return {ok: true, json: async () => ({items: entities})};
        },
        ...overrides,
    });
    return {elements, calls, controller};
}

test('promote dialog performs a read-only feasibility check and offers no write action', async () => {
    const {elements, calls, controller} = previewController();
    controller.open('promote', {entity_id: 2, name: 'Объект Б', code: 'OBJ-002'});
    assert.equal(elements.get('identityPromoteModal').hidden, false);
    assert.equal(elements.get('identityPromoteName').value, 'Объект Б');
    assert.equal(elements.get('identityPromoteCode').value, 'OBJ-002');
    assert.equal(elements.get('identityPromoteCode').disabled, false);
    assert.deepEqual(elements.get('identityPromoteParent').children.map(option => option.value), ['', '1']);
    elements.get('identityPromoteParent').value = '1';
    elements.get('identityPromoteName').value = 'Новое название';
    await elements.get('identityPromoteCheck').handlers.click();
    assert.deepEqual(calls.map(call => [call.url, call.options.method]), [['/api/construction-entities', 'GET']]);
    assert.match(elements.get('identityPromoteResult').textContent, /не выполнено/);
    assert.equal(elements.get('identityPromoteResult').hidden, false);
    assert.equal(elements.get('identityPromoteCode').value, 'OBJ-002');
    assert.equal(elements.get('identityPromoteName').value, 'Новое название');
});

test('confirmed test conversion checks database before PATCH and refreshes only after success',async()=>{
    const entities=catalog().map(e=>({...e,version:1})),calls=[],saved=[];
    const p=previewController(entities,{enablePromote:true,confirmOperation:()=>true,onSaved:async item=>saved.push(item),
        request:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>url.endsWith('/environment')
            ?{item:{profile:'test',database:'ai_excel_agent_test',schema:'test_construction_identity_stage46'}}
            :options.method==='PATCH'?{item:{entity_id:2,parent_entity_id:1}}:{items:entities}};}});
    p.controller.open('promote',entities[1]);p.elements.get('identityPromoteParent').value='1';
    await p.controller.check();
    assert.deepEqual(calls.map(c=>c[1].method),['GET','GET','PATCH']);
    assert.deepEqual(JSON.parse(calls[2][1].body),{parent_entity_id:1,version:1,confirmed:true});
    assert.equal(saved.length,1);assert.equal(p.elements.get('identityPromoteModal').hidden,true);
});

test('cancellation, stale version, wrong database and server conflict never refresh the tree',async()=>{
    for(const mode of ['cancel','version','database','conflict']){
        const entities=catalog().map(e=>({...e,version:1})),calls=[];let refreshed=0;
        const p=previewController(entities,{enablePromote:true,confirmOperation:()=>mode!=='cancel',onSaved:async()=>refreshed++,
            request:async(url,options)=>{calls.push(options.method);return {ok:options.method!=='PATCH',json:async()=>url.endsWith('/environment')
                ?{item:{profile:'test',database:mode==='database'?'wrong':'ai_excel_agent_test',schema:'test_construction_identity_stage46'}}
                :options.method==='PATCH'?{message:'Конфликт версии'}:{items:entities}};}});
        p.controller.open('promote',{...entities[1],version:mode==='version'?2:1});p.elements.get('identityPromoteParent').value='1';
        await p.controller.check();assert.equal(refreshed,0);assert.equal(p.elements.get('identityPromoteModal').hidden,false);
        assert.equal(calls.includes('PATCH'),mode==='conflict');
    }
});

test('standalone dialog checks eligibility using GET only', async () => {
    const {elements, calls, controller} = previewController();
    controller.open('standalone', {entity_id: 3, name: 'Подобъект В', code: 'SUB-001'});
    assert.equal(elements.get('identityStandaloneName').value, 'Подобъект В');
    assert.equal(elements.get('identityStandaloneCode').value, 'SUB-001');
    await elements.get('identityStandaloneCheck').handlers.click();
    assert.deepEqual(calls.map(call => call.options.method), ['GET']);
    assert.match(elements.get('identityStandaloneResult').textContent, /не выполнено/);
    assert.equal(elements.get('identityStandaloneModal').hidden, false);
});

test('standalone confirmation sends null parent and refreshes once',async()=>{
    const entities=catalog().map(e=>({...e,version:1})),calls=[];let refreshed=0;
    const p=previewController(entities,{enableStandalone:true,confirmOperation:()=>true,onSaved:async()=>refreshed++,
        request:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>url.endsWith('/environment')
            ?{item:{profile:'test',database:'ai_excel_agent_test',schema:'test_construction_identity_stage46'}}
            :options.method==='PATCH'?{item:{entity_id:3,parent_entity_id:null}}:{items:entities}};}});
    p.controller.open('standalone',entities[2]);await p.controller.check();await p.controller.check();
    assert.deepEqual(JSON.parse(calls.find(c=>c[1].method==='PATCH')[1].body),{parent_entity_id:null,version:1,confirmed:true});
    assert.equal(refreshed,1);assert.equal(p.elements.get('identityStandaloneModal').hidden,true);
});

test('standalone errors and cancelled confirmation leave tree unchanged',async()=>{
    for(const mode of ['cancel','schema','conflict','refresh']){
        const entities=catalog().map(e=>({...e,version:1}));let writes=0,refreshes=0;
        const p=previewController(entities,{enableStandalone:true,confirmOperation:()=>mode!=='cancel',
            onSaved:async()=>{refreshes++;throw new Error('offline');},request:async(url,options)=>{
                if(options.method==='PATCH')writes++;
                return {ok:!(options.method==='PATCH'&&mode==='conflict'),json:async()=>url.endsWith('/environment')
                    ?{item:{profile:'test',database:'ai_excel_agent_test',schema:mode==='schema'?'test_other':'test_construction_identity_stage46'}}
                    :options.method==='PATCH'?{message:'Конфликт',item:{entity_id:3,parent_entity_id:null}}:{items:entities}};
            }});
        p.controller.open('standalone',entities[2]);await p.controller.check();
        assert.equal(refreshes,mode==='refresh'?1:0);assert.equal(p.elements.get('identityStandaloneModal').hidden,false);
        if(mode==='refresh'){await p.controller.check();assert.equal(writes,1);assert.match(p.elements.get('identityStandaloneResult').textContent,/сохранено/);}
        else assert.equal(writes,mode==='conflict'?1:0);
    }
});

test('production template hides dialogs and page flag disables preview actions', () => {
    const template = fs.readFileSync('app/templates/processing.html', 'utf8');
    const main = fs.readFileSync('app/main.py', 'utf8');
    const processing = fs.readFileSync('app/static/js/processing.js', 'utf8');
    assert.match(template, /{% if test_mode %}[\s\S]*id="identityPromoteModal"[\s\S]*id="identityStandaloneModal"[\s\S]*{% endif %}/);
    assert.match(main, /test_mode["']?\s*:\s*os\.getenv\(["']APP_DB_PROFILE["']\)\s*==\s*["']test["']/);
    assert.match(processing, /dataset\.identityPreviewEnabled === "true"/);
});
