const {test}=require('node:test');
const assert=require('node:assert/strict');
const {objectHierarchyRows,renderObjectHierarchy,createSubobjectDirectoryEditor}=require('../app/static/js/object_hierarchy.js');
const parents=[{id:2,name:'Якорь'},{id:1,name:'Арка'},{id:3,name:'Мост'}];
const children=[{id:11,object_id:1,name:'Яма',is_active:true},{id:12,object_id:1,name:'Дорога',is_active:true},
    {id:13,object_id:2,name:'Подъезд',is_active:false}];
class Element {
    constructor(tag='div'){Object.assign(this,{tag,children:[],handlers:{},dataset:{},value:'',disabled:false,hidden:false});}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    addEventListener(name,fn){this.handlers[name]=fn;}
    focus(){this.focused=true;}
}
const walk=x=>[x,...x.children.flatMap(walk)];
test('parents and children sort alphabetically without mixing parents',()=>{
    const rows=objectHierarchyRows(parents,children,{activity:'all'});
    assert.deepEqual(rows.map(x=>x.item.name),['Арка','Мост','Якорь']);
    assert.deepEqual(rows[0].children.map(x=>x.name),['Дорога','Яма']);
    assert.equal(rows[2].children[0].object_id,2);
});
test('descending, ID and child count sorting',()=>{
    assert.deepEqual(objectHierarchyRows(parents,children,{sort:'desc'}).map(x=>x.item.id),[2,3,1]);
    assert.deepEqual(objectHierarchyRows(parents,children,{sort:'id'}).map(x=>x.item.id),[1,2,3]);
    assert.equal(objectHierarchyRows(parents,children,{sort:'count'})[0].item.id,1);
});
test('child search returns its parent and automatically opens it',()=>{
    const rows=objectHierarchyRows(parents,children,{query:'дорога'});
    assert.equal(rows.length,1);assert.equal(rows[0].item.name,'Арка');assert.ok(rows[0].forceOpen);
    assert.deepEqual(rows[0].children.map(x=>x.name),['Дорога']);
});
test('parent search includes children; empty and missing search',()=>{
    assert.equal(objectHierarchyRows(parents,children,{query:'Арка'})[0].children.length,2);
    assert.equal(objectHierarchyRows(parents,children,{query:'Неизвестный'}).length,0);
    assert.equal(objectHierarchyRows(parents,children).length,3);
});
test('with and without children follow selected activity',()=>{
    assert.deepEqual(objectHierarchyRows(parents,children,{presence:'with'}).map(x=>x.item.id),[1]);
    assert.deepEqual(objectHierarchyRows(parents,children,{presence:'without'}).map(x=>x.item.id),[3,2]);
    assert.equal(objectHierarchyRows(parents,children,{presence:'with',activity:'all'}).length,2);
});
test('inactive filter exposes inactive children and keeps correct active count',()=>{
    const row=objectHierarchyRows(parents,children,{activity:'inactive',query:'Подъезд'})[0];
    assert.equal(row.active,0);assert.equal(row.total,1);assert.equal(row.children[0].is_active,false);
});
function render(){
    const container=new Element(),expanded=new Set(),events=[];
    renderObjectHierarchy(container,objectHierarchyRows(parents,children,{activity:'all'}),{
        expanded,activity:'all',document:{createElement:tag=>new Element(tag)},onAdd:x=>events.push(['add',x]),onEdit:x=>events.push(['edit',x])});
    return {container,expanded,events};
}
test('DOM expand/collapse updates retained state and displays counts',()=>{
    const {container,expanded}=render();const parent=container.children[0];
    assert.equal(parent.open,false);parent.open=true;parent.handlers.toggle();assert.ok(expanded.has(1));
    parent.open=false;parent.handlers.toggle();assert.ok(!expanded.has(1));
    assert.ok(walk(parent).some(x=>x.textContent==='Подобъектов: 2 · Активных: 2'));
});
test('DOM renders inactive status and routes add/edit to their parent',()=>{
    const {container,events}=render();
    assert.ok(walk(container).some(x=>x.textContent==='Неактивен'));
    walk(container.children[0]).find(x=>x.textContent==='+ Добавить подобъект').handlers.click();
    walk(container.children[0]).find(x=>x.textContent==='Редактировать').handlers.click();
    assert.equal(events[0][1].id,1);assert.equal(events[1][1].object_id,1);
    assert.ok(walk(container).some(x=>x.className?.includes('edit-object-directory')));
    assert.ok(walk(container).some(x=>x.className?.includes('delete-object-directory')));
});
function editor({used=false,fail=false}={}){
    const ids={},calls=[],saved=[];
    const doc={getElementById:id=>ids[id] ||= new Element(),createElement:tag=>new Element(tag)};
    const request=async(url,options)=>{
        const payload=JSON.parse(options.body);calls.push({url,method:options.method,payload});
        if(fail)return {ok:false,status:409,json:async()=>({message:'Подобъект с таким названием уже существует'})};
        return {ok:true,status:200,json:async()=>url.endsWith('/check')?{item:{requires_confirmation:used,linked_facts:8,missing_assignments:3,old_object_name:'Арка',object_name:'Якорь',confirmation_token:'token'}}:
            {item:{id:11,object_id:payload.object_id || 1,name:payload.name,is_active:payload.is_active ?? true}}};
    };
    const controller=createSubobjectDirectoryEditor({document:doc,getObjects:()=>parents,onSaved:async(...args)=>saved.push(args),request});
    const submit=()=>ids.subobjectDirectoryForm.handlers.submit({preventDefault(){}});
    return {ids,calls,saved,controller,submit};
}
test('add has fixed known parent and uses existing POST',async()=>{
    const e=editor();e.controller.open(parents[1]);
    assert.equal(e.ids.subobjectDirectoryParent.value,'1');assert.ok(e.ids.subobjectDirectoryParent.disabled);
    e.ids.subobjectDirectoryName.value='Новый';await e.submit();
    assert.deepEqual(e.calls[0],{url:'/api/subobjects',method:'POST',payload:{object_id:1,name:'Новый'}});
    assert.equal(e.saved.length,1);assert.ok(e.ids.subobjectDirectoryModal.hidden);
});
test('rename and deactivate use PATCH, can reactivate',async()=>{
    const e=editor();e.controller.open(null,children[0]);
    e.ids.subobjectDirectoryName.value='Новое имя';e.ids.subobjectDirectoryActive.value='false';await e.submit();
    assert.deepEqual(e.calls[0].payload,{name:'Новое имя',is_active:false});assert.equal(e.calls[0].method,'PATCH');
    e.controller.open(null,{...children[0],is_active:false});e.ids.subobjectDirectoryActive.value='true';await e.submit();
    assert.equal(e.calls[1].payload.is_active,true);
});
test('unused move previews then transfers without journal confirmation',async()=>{
    const e=editor();e.controller.open(null,children[0]);e.ids.subobjectDirectoryParent.value='2';await e.submit();
    assert.equal(e.calls[0].url,'/api/subobjects/11/move/check');assert.equal(e.calls[0].method,'POST');
    assert.equal(e.calls[1].url,'/api/subobjects/11/move');assert.equal(e.calls[1].payload.object_id,2);
    assert.equal(e.saved[0][0].object_id,2);
});
test('used move displays old/new parents, facts and warning; explicit confirmation sends token',async()=>{
    const e=editor({used:true});e.controller.open(null,children[0]);e.ids.subobjectDirectoryParent.value='2';await e.submit();
    assert.equal(e.calls.length,1);assert.equal(e.saved.length,0);
    assert.match(e.ids.subobjectDirectoryConfirmation.textContent,/Старый объект: Арка/);
    assert.match(e.ids.subobjectDirectoryConfirmation.textContent,/Новый объект: Якорь/);
    assert.match(e.ids.subobjectDirectoryConfirmation.textContent,/Журнала: 8/);
    assert.match(e.ids.subobjectDirectoryConfirmation.textContent,/отсутствует назначение/);
    assert.equal(e.ids.subobjectDirectorySave.textContent,'Перенести');await e.submit();
    assert.equal(e.calls[1].payload.confirmation_token,'token');assert.equal(e.saved.length,1);
});
test('cancel used move never transfers; editing fields invalidates preview',async()=>{
    const e=editor({used:true});e.controller.open(null,children[0]);e.ids.subobjectDirectoryParent.value='2';await e.submit();
    e.ids.subobjectDirectoryName.value='Изменённое';e.ids.subobjectDirectoryName.handlers.input();
    await e.submit();assert.equal(e.calls.length,2);assert.ok(e.calls.every(x=>x.url.endsWith('/check')));
    e.ids.subobjectDirectoryCancel.handlers.click();assert.ok(e.ids.subobjectDirectoryModal.hidden);assert.equal(e.saved.length,0);
});
test('empty and duplicate names display useful errors without closing modal',async()=>{
    const e=editor({fail:true});e.controller.open(parents[1]);await e.submit();assert.equal(e.calls.length,0);
    e.ids.subobjectDirectoryName.value='Дубль';await e.submit();
    assert.equal(e.ids.subobjectDirectoryError.textContent,'Такой подобъект уже существует у этого объекта.');
    assert.equal(e.ids.subobjectDirectoryModal.hidden,false);assert.equal(e.ids.subobjectDirectorySave.disabled,false);
});

test('modal stays busy until refreshed directory is ready',async()=>{
    const ids={};let finish;
    const doc={getElementById:id=>ids[id] ||= new Element(),createElement:tag=>new Element(tag)};
    const refreshed=new Promise(resolve=>{finish=resolve;});
    const controller=createSubobjectDirectoryEditor({document:doc,getObjects:()=>parents,
        request:async()=>({ok:true,status:200,json:async()=>({item:{id:20,object_id:1,name:'Новый'}})}),
        onSaved:()=>refreshed});
    controller.open(parents[1]);ids.subobjectDirectoryName.value='Новый';
    const pending=ids.subobjectDirectoryForm.handlers.submit({preventDefault(){}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(ids.subobjectDirectoryModal.hidden,false);assert.ok(ids.subobjectDirectorySave.disabled);
    finish();await pending;assert.equal(ids.subobjectDirectoryModal.hidden,true);
});
