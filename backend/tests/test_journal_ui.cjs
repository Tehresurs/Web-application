const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Element {
    constructor(tag='div',text='',value='') { Object.assign(this,{tag,textContent:text,value,children:[],handlers:{},checked:false}); }
    append(...children) { this.children.push(...children); }
    add(child) { this.append(child); }
    replaceChildren(...children) { this.children=children; }
    addEventListener(name,fn) { this.handlers[name]=fn; }
    get options() { return this.children; }
    get selectedOptions() { return this.children.filter(item=>item.value===this.value); }
}
const walk=node=>[node,...node.children.flatMap(walk)];
const settle=()=>new Promise(resolve=>setImmediate(resolve));

function setup() {
    const ids={};
    for (const id of ['journalSubcontractor','journalFrom','journalTo','journalView','journalEmployee','journalObject','journalIncludeSubobjects',
        'journalIncludeLabel','journalMessage','journalGroups','journalSummary','journalFilters','journalEntityFilters',
        'journalEmployeeLabel','journalObjectLabel','journalNavButton','journalPage']) ids[id]=new Element();
    ids.journalView.value='object';
    ids.journalIncludeSubobjects.checked=true;
    ids.journalEmployee.add(new Element('option','Все инженеры',''));
    ids.journalObject.add(new Element('option','Все объекты / подобъекты',''));
    const requests=[];
    const parent={id:1,employee_id:1,full_name:'Инженер',object_id:1,object_name:'Куст',subobject_id:null,
        control_item_key:'object:1',control_item_type:'object',control_item_name:'Куст',report_date:'2026-09-03',
        po_name:'ПО',category_name:'Категория',source_file:'parent.docx'};
    const child={...parent,id:2,subcontractor_id:27,subcontractor_name:'Subcontractor',subobject_id:1,subobject_name:'Подъезд',control_item_key:'subobject:1',control_item_type:'subobject',control_item_name:'Подъезд',source_file:'child.docx'};
    const context={Date,URLSearchParams,AbortController,Option:function(text,value){return new Element('option',text,value);},
        document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),querySelectorAll:()=>[]},showMainSection(){},
        fetch:async url=>{
            requests.push(url);
            const q=new URL(url,'http://test').searchParams;
            let items=q.has('subobject_id')?[child]:q.get('include_subobjects')==='false'?[parent]:[parent,child];
            if(q.has('subcontractor_id')) items=items.filter(x=>String(x.subcontractor_id)===q.get('subcontractor_id'));
            const pairs=items.map(row=>({...row,dates:['2026-09-03'],days_count:1,fact_ids:[row.id]}));
            const groups=q.get('view')==='employee'?[{employee_id:1,full_name:'Инженер',items:pairs}]:pairs.map(pair=>({...pair,items:[pair]}));
            return {ok:true,json:async()=>({date_from:q.get('date_from'),date_to:q.get('date_to'),view:q.get('view'),
                filters:{employee_id:q.get('employee_id'),object_id:q.get('object_id'),subobject_id:q.get('subobject_id')},
                items,groups,dates:['2026-09-03'],summary:{objects_count:1,subobjects_count:items.some(x=>x.subobject_id)?1:0,employees_count:1,days_count:1,facts_count:items.length},
                options:{subcontractors:[{id:27,name:'Subcontractor'}],employees:[{employee_id:1,full_name:'Инженер'}],control_items:[parent,child]}})};
        }};
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('app/static/js/journal.js','utf8'),context);
    ids.journalFrom.value='2026-09-01';ids.journalTo.value='2026-09-30';
    return {ids,requests};
}

test('journal loads one filtered response, renders six columns and retains sources',async()=>{
    const {ids,requests}=setup();
    ids.journalFilters.handlers.submit({preventDefault(){}});
    await settle();
    assert.equal(requests.length,1);
    const nodes=walk(ids.journalGroups);
    assert.deepEqual(nodes.filter(x=>x.tag==='th').slice(0,6).map(x=>x.textContent),['Дата','Инженер','Объект / Подобъект','ПО','Субподрядчик','Категория']);
    assert.ok(nodes.some(x=>x.textContent==='child.docx'));
    assert.ok(nodes.some(x=>x.textContent==='parent.docx'));
    assert.ok(ids.journalObject.options.some(x=>x.value==='object:1'));
    assert.ok(ids.journalObject.options.some(x=>x.value==='subobject:1'));
    assert.match(ids.journalSummary.textContent,/Основных объектов: 1 · Подобъектов: 1/);
});

test('clicking child then engineer preserves child and opens unique dates',async()=>{
    const {ids,requests}=setup();
    ids.journalFilters.handlers.submit({preventDefault(){}});await settle();
    walk(ids.journalGroups).find(x=>x.tag==='button'&&x.textContent==='Подъезд').handlers.click();await settle();
    let q=new URL(requests.at(-1),'http://test').searchParams;
    assert.equal(q.get('subobject_id'),'1');
    assert.equal(ids.journalIncludeLabel.hidden,true);
    walk(ids.journalGroups).find(x=>x.tag==='button'&&x.textContent==='Инженер').handlers.click();await settle();
    q=new URL(requests.at(-1),'http://test').searchParams;
    assert.equal(q.get('employee_id'),'1');assert.equal(q.get('subobject_id'),'1');
    assert.equal(q.get('date_from'),'2026-09-01');assert.equal(q.get('date_to'),'2026-09-30');
    assert.equal(q.get('view'),'employee');
    assert.ok(walk(ids.journalGroups).some(x=>x.tag==='details'&&x.open===true));
    assert.match(ids.journalSummary.textContent,/Даты контроля: 03.09.2026/);
});

test('parent checkbox is visible only for parent and filters in the backend query',async()=>{
    const {ids,requests}=setup();
    ids.journalFilters.handlers.submit({preventDefault(){}});await settle();
    ids.journalObject.value='object:1';ids.journalObject.handlers.change();
    assert.equal(ids.journalIncludeLabel.hidden,false);
    ids.journalIncludeSubobjects.checked=false;
    ids.journalFilters.handlers.submit({preventDefault(){}});await settle();
    assert.equal(new URL(requests.at(-1),'http://test').searchParams.get('include_subobjects'),'false');
    assert.ok(!walk(ids.journalGroups).some(x=>x.textContent==='child.docx'));
});

test('subcontractor dropdown filters facts and remains selected during history navigation',async()=>{
    const {ids,requests}=setup();
    ids.journalFilters.handlers.submit({preventDefault(){}});await settle();
    let nodes=walk(ids.journalGroups);
    assert.ok(nodes.some(x=>x.tag==='td'&&x.textContent==='—'));
    assert.ok(nodes.some(x=>x.tag==='td'&&x.textContent==='Subcontractor'));
    assert.equal(ids.journalSubcontractor.options[0].value,'');
    ids.journalSubcontractor.value='27';ids.journalSubcontractor.handlers.change();
    ids.journalFilters.handlers.submit({preventDefault(){}});await settle();
    assert.equal(new URL(requests.at(-1),'http://test').searchParams.get('subcontractor_id'),'27');
    assert.ok(!walk(ids.journalGroups).some(x=>x.textContent==='parent.docx'));
    walk(ids.journalGroups).find(x=>x.tag==='button'&&x.textContent==='Инженер').handlers.click();await settle();
    assert.equal(new URL(requests.at(-1),'http://test').searchParams.get('subcontractor_id'),'27');
    assert.equal(ids.journalSubcontractor.value,'27');
});
