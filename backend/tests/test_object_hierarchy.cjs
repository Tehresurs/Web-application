const {test}=require('node:test');
const assert=require('node:assert/strict');
const {objectHierarchyRows,objectCatalogRows,renderObjectHierarchy,createSubobjectDirectoryEditor}=require('../app/static/js/object_hierarchy.js');
const parents=[{id:2,name:'Якорь'},{id:1,name:'Арка'},{id:3,name:'Мост'}];
const children=[{id:11,object_id:1,name:'Яма',is_active:true},{id:12,object_id:1,name:'Дорога',is_active:true},
    {id:13,object_id:2,name:'Подъезд',is_active:false}];
class Element {
    constructor(tag='div'){Object.assign(this,{tag,children:[],handlers:{},dataset:{},attributes:{},value:'',disabled:false,hidden:false,className:''});}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    addEventListener(name,fn){this.handlers[name]=fn;}
    setAttribute(name,value){this.attributes[name]=String(value);}
    focus(){this.focused=true;}
}
const walk=x=>[x,...x.children.flatMap(walk)];
test('promoted roots without legacy IDs keep separate selection and children',()=>{
    const roots=[{id:null,entity_id:501,name:'Первый'},{id:null,entity_id:502,name:'Второй'}];
    const kids=[{id:71,entity_id:601,name:'Ребёнок 1',is_active:true,current_hierarchy:{parent_entity_id:501}},
        {id:72,entity_id:602,name:'Ребёнок 2',is_active:true,current_hierarchy:{parent_entity_id:502}}];
    const container=new Element();
    renderObjectHierarchy(container,objectHierarchyRows(roots,kids),{testMode:true,expanded:new Set(['entity:501','entity:502']),
        selectedId:'entity:502',onAdd:()=>{},onEdit:()=>{},document:{createElement:tag=>new Element(tag)}});
    const rows=walk(container).filter(n=>n.tag==='tr'&&n.dataset.entityId);
    assert.equal(rows.length,4);
    assert.equal(rows.filter(n=>n.attributes['aria-selected']==='true').length,1);
    assert.equal(rows.find(n=>n.attributes['aria-selected']==='true').dataset.entityId,'502');
    assert.equal(rows.filter(n=>n.dataset.entityId==='601').length,1);
    assert.equal(rows.filter(n=>n.dataset.entityId==='602').length,1);
});
test('floating menu opens upward near bottom and stays within narrow viewport',()=>{
    const {objectMenuPosition}=require('../app/static/js/object_hierarchy.js');
    const up=objectMenuPosition({top:700,bottom:730,right:980},{width:220,height:180},{width:1000,height:768});
    assert.equal(up.up,true);assert.equal(up.top,515);assert.equal(up.left,760);
    const down=objectMenuPosition({top:20,bottom:50,right:100},{width:220,height:180},{width:320,height:768});
    assert.equal(down.up,false);assert.equal(down.left,8);assert.equal(down.top,55);
});
test('archived records offer restoration without conversion or deletion',()=>{
    const roots=[{id:1,name:'Архивный родитель',is_archived:true}];
    const kids=[{id:22,object_id:1,name:'Архивный ребёнок',is_active:true,is_archived:true,parent_is_archived:true}];
    const container=new Element();
    renderObjectHierarchy(container,objectHierarchyRows(roots,kids,{activity:'all'}),{
        expanded:new Set([1]),testMode:true,parents:roots,document:{createElement:tag=>new Element(tag)},
        onAdd:()=>{},onEdit:()=>{},onPromote:()=>{},onMakeStandalone:()=>{},
    });
    const labels=walk(container).filter(n=>n.tag==='button').map(n=>n.textContent);
    assert.equal(labels.filter(v=>v==='Восстановить из архива').length,2);
    assert.ok(!labels.some(v=>/Преобразовать|Сделать самостоятельным|Создать подобъект|Удалить/.test(v)));
});
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
test('test catalog tabs separate roots, children, all records, and archived records',()=>{
    const roots=[
        {id:1,entity_id:101,name:'Активный объект',is_archived:false,activity_status:'ACTIVE'},
        {id:2,entity_id:102,name:'Архивный объект',is_archived:true,activity_status:'ACTIVE'},
    ];
    const items=[
        {id:11,entity_id:111,object_id:1,name:'Активный подобъект',is_archived:false,is_active:true,
            current_hierarchy:{parent_entity_id:101}},
        {id:12,entity_id:112,object_id:1,name:'Архивный подобъект',is_archived:true,is_active:true,
            current_hierarchy:{parent_entity_id:101}},
        {id:13,entity_id:113,object_id:2,name:'Подобъект архивного объекта',is_archived:false,is_active:true,
            parent_is_archived:true,current_hierarchy:{parent_entity_id:102}},
    ];
    const all=objectCatalogRows(roots,items,{view:'all'});
    assert.equal(all.length,1);assert.deepEqual(all[0].children.map(item=>item.name),['Активный подобъект']);
    const standalone=objectCatalogRows(roots,items,{view:'standalone'});
    assert.equal(standalone.length,1);assert.equal(standalone[0].children.length,0);
    const childrenView=objectCatalogRows(roots,items,{view:'children'});
    assert.equal(childrenView.length,1);assert.equal(childrenView[0].children[0].id,11);
    const archived=objectCatalogRows(roots,items,{view:'archived'});
    assert.deepEqual(archived.map(row=>row.item.id),[1,2]);
    assert.deepEqual(archived[0].children.map(item=>item.id),[12]);
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
test('identity preview actions are opt-in and route parent and child to separate dialogs',()=>{
    const calls=[];
    const container=new Element();
    const options={expanded:new Set(),activity:'all',document:{createElement:tag=>new Element(tag)},
        onAdd:()=>{},onEdit:()=>{},onPromote:item=>calls.push(['promote',item]),onMakeStandalone:item=>calls.push(['standalone',item])};
    renderObjectHierarchy(container,objectHierarchyRows(parents,children,{activity:'all'}),options);
    const nodes=walk(container);
    nodes.find(x=>x.textContent==='Преобразовать в подобъект').handlers.click();
    nodes.find(x=>x.textContent==='Сделать самостоятельным объектом').handlers.click();
    assert.equal(calls[0][0],'promote');assert.equal(calls[0][1].id,1);
    assert.equal(calls[1][0],'standalone');assert.equal(calls[1][1].id,12);
    const productionContainer=new Element();
    renderObjectHierarchy(productionContainer,objectHierarchyRows(parents,children,{activity:'all'}),{
        expanded:new Set(),onAdd:()=>{},onEdit:()=>{},document:{createElement:tag=>new Element(tag)}});
    assert.ok(!walk(productionContainer).some(x=>x.textContent?.includes('Преобразовать в подобъект')));
    assert.ok(!walk(productionContainer).some(x=>x.textContent?.includes('Сделать самостоятельным объектом')));
});
test('identity children render under their current parent without a legacy object ID',()=>{
    const roots=[{id:1,entity_id:101,name:'Текущий родитель',current_hierarchy:{entity_id:101}}];
    const currentChildren=[{id:12,entity_id:102,object_id:null,name:'Текущий ребёнок',is_active:true,
        current_hierarchy:{entity_id:102,parent_entity_id:101}}];
    const container=new Element(),events=[];
    renderObjectHierarchy(container,objectHierarchyRows(roots,currentChildren),{
        expanded:new Set(),activity:'active',document:{createElement:tag=>new Element()},
        onAdd:()=>{},onEdit:()=>{},onMakeStandalone:child=>events.push(child)});
    assert.ok(walk(container).some(x=>x.textContent==='Текущий ребёнок'));
    walk(container).find(x=>x.textContent==='Сделать самостоятельным объектом').handlers.click();
    assert.equal(events[0].entity_id,102);
});
test('test mode groups object actions in one menu and marks archived status',()=>{
    const roots=[{id:1,name:'Объект',is_archived:false,activity_status:'ACTIVE'}];
    const kids=[{id:22,object_id:1,name:'Подобъект',is_active:true,is_archived:false}];
    const container=new Element();
    renderObjectHierarchy(container,objectHierarchyRows(roots,kids),{
        expanded:new Set([1]),activity:'all',testMode:true,parents:roots,document:{createElement:tag=>new Element(tag)},
        onAdd:()=>{},onEdit:()=>{},onPromote:()=>{},onMakeStandalone:()=>{},
    });
    const nodes=walk(container);
    assert.equal(nodes.filter(node=>node.className==='object-action-menu').length,2);
    assert.equal(nodes.filter(node=>node.tag==='summary'&&node.textContent==='⋯').length,2);
    assert.ok(nodes.some(node=>node.className.includes('object-catalog-icon')));
    assert.ok(nodes.some(node=>node.className==='object-catalog-root-row'));
    assert.ok(nodes.some(node=>node.textContent==='Создать подобъект'));
    assert.ok(nodes.some(node=>node.textContent==='Преобразовать в подобъект'));
    assert.ok(nodes.some(node=>node.textContent==='Сделать самостоятельным объектом'));
    assert.ok(nodes.some(node=>node.textContent==='Действующий'));
    assert.ok(nodes.every(node=>node.textContent!=='Редактировать объект'));
    assert.ok(nodes.some(node=>(node.className||'').includes('archive-object-directory')&&node.dataset.id==='1'));
    assert.ok(nodes.some(node=>(node.className||'').includes('archive-subobject-directory')&&node.dataset.id==='22'));
});
test('test mode renders a six-column hierarchy table and offers no third-level creation',()=>{
    const roots=[{id:1,entity_id:101,name:'Объект',code:'OBJ-001',activity_status:'ACTIVE'}];
    const kids=[{id:22,entity_id:202,object_id:1,name:'Подобъект',code:'SUB-001',is_active:true,
        current_hierarchy:{entity_id:202,parent_entity_id:101}}];
    const container=new Element();
    renderObjectHierarchy(container,objectHierarchyRows(roots,kids,{activity:'all'}),{
        expanded:new Set([1]),activity:'all',testMode:true,parents:roots,document:{createElement:tag=>new Element(tag)},
        onAdd:()=>{},onEdit:()=>{},onPromote:()=>{},onMakeStandalone:()=>{},
    });
    const nodes=walk(container);
    const table=nodes.find(node=>node.className==='ui-table object-catalog-table');
    assert.ok(table);
    assert.deepEqual(table.children[0].children[0].children.map(cell=>cell.textContent),
        ['Наименование','Тип','Статус','Родительский объект','Код','Действия']);
    assert.ok(nodes.some(node=>node.textContent==='OBJ-001'));
    assert.ok(nodes.some(node=>node.textContent==='SUB-001'));
    assert.ok(nodes.some(node=>node.textContent==='Объект'));
    assert.ok(nodes.some(node=>node.textContent==='Подобъект'));
    const childRow=nodes.find(node=>node.className==='object-catalog-child-row');
    assert.ok(childRow);
    assert.ok(!walk(childRow).some(node=>(node.className||'').includes('add-subobject-directory')));
    assert.ok(nodes.some(node=>(node.className||'').includes('add-subobject-directory')));
    let selected=null;
    renderObjectHierarchy(container,objectHierarchyRows(roots,kids,{activity:'all'}),{
        expanded:new Set([1]),activity:'all',testMode:true,parents:roots,document:{createElement:tag=>new Element(tag)},
        onSelect:id=>{selected=id;},onAdd:()=>{},onEdit:()=>{},
    });
    walk(container).find(node=>node.className==='object-catalog-child-row').handlers.click({target:{closest:()=>null}});
    assert.equal(selected,22);
});
test('test mode uses employee badge tones and selected-row semantics for object statuses',()=>{
    const roots=[
        {id:1,name:'Активный',activity_status:'ACTIVE'},
        {id:2,name:'Приостановлен',activity_status:'SUSPENDED'},
        {id:3,name:'Завершён',activity_status:'COMPLETED'},
        {id:4,name:'Архив',is_archived:true},
    ];
    const container=new Element();
    renderObjectHierarchy(container,objectHierarchyRows(roots,[],{activity:'all'}),{
        expanded:new Set([1]),activity:'all',testMode:true,selectedId:1,document:{createElement:tag=>new Element(tag)},
        onAdd:()=>{},onEdit:()=>{},
    });
    const nodes=walk(container);
    assert.ok(nodes.some(node=>node.textContent==='Действующий'&&node.className.includes('badge-green')));
    assert.ok(nodes.some(node=>node.textContent==='Приостановлен'&&node.className.includes('badge-orange')));
    assert.ok(nodes.some(node=>node.textContent==='Завершён'&&node.className.includes('badge-neutral')));
    assert.ok(nodes.some(node=>node.textContent==='Архив'&&node.className.includes('ui-badge-muted')));
    const firstRow=nodes.find(node=>node.className==='object-catalog-root-row'&&node.dataset.recordId==='1');
    assert.equal(firstRow.attributes['aria-selected'],'true');
    const archivedRow=nodes.find(node=>node.className==='object-catalog-root-row'&&node.dataset.recordId==='4');
    assert.equal(archivedRow.attributes['aria-selected'],'false');
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
