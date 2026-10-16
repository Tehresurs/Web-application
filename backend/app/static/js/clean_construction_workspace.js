/* Loaded only by the server-validated clean-start workspace, never the legacy page. */
function createCleanCatalog(request = fetch) {
    const base = '/api/clean-construction-entities';
    async function api(path = '', method = 'GET', payload) {
        const response = await request(base + path, {method, headers: {'Content-Type':'application/json'},
            body: payload === undefined ? undefined : JSON.stringify(payload)});
        const result = await response.json();
        if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : result.message || 'Не удалось выполнить операцию');
        return result;
    }
    return {api, async verify() {
        const {item} = await api('/environment');
        if (item.profile !== 'test' || item.contract !== 'entity_id' || item.schema !== 'public') throw Error('Тестовое окружение не подтверждено');
    }, save(item, fields, parent = null) {
        return item ? api(`/${item.entity_id}`, 'PATCH', {...fields, version:item.version})
            : api('', 'POST', {...fields, parent_entity_id:parent?.entity_id ?? null});
    }, archive(item) {return api(`/${item.entity_id}/${item.is_archived ? 'restore' : 'archive'}`, 'POST', {version:item.version});}};
}

async function startCleanWorkspace(doc = document) {
    const get = id => doc.getElementById(id), catalog = createCleanCatalog();
    await catalog.verify();
    // Keep other sections inert; their legacy controllers are not loaded on this page.
    for (const section of doc.querySelectorAll('main > section')) section.hidden = true;
    get('objectsPage').hidden = false;
    const list = get('objectList'), modal = get('objectDirectoryModal'), error = get('objectDirectoryModalError');
    let items = [], editing = null, parent = null, busy = false, view = 'all', selectedId = null;
    const expanded = new Set();
    const preview = createConstructionIdentityPreview({cleanStart:true, enablePromote:true, enableStandalone:true,
        getKnownEntities:()=>items, onSaved:async()=>{view='all'; await load();}});
    function render() {
        const roots = items.filter(i=>i.parent_entity_id == null), children = items.filter(i=>i.parent_entity_id != null);
        const rows = objectCatalogRows(roots, children, {view, activity:get('objectStatusFilter').value,
            query:get('objectSearchInput').value, sort:get('objectSort').value});
        renderObjectHierarchy(list, rows, {expanded, testMode:true, parents:roots, selectedId,
            onSelect:id=>{selectedId=id;render();}, onAdd:item=>open(null,item), onEdit:item=>open(item),
            onRootEdit:item=>open(item), onArchive:archive,
            onPromote:item=>preview.open('promote',item), onMakeStandalone:item=>preview.open('standalone',item)});
        get('objectCount').textContent=`Записей: ${items.length}`;
        for (const tab of doc.querySelectorAll('[data-object-view]')) {
            tab.classList.toggle('active',tab.dataset.objectView===view);
            tab.setAttribute('aria-selected',String(tab.dataset.objectView===view));
        }
    }
    async function load() {
        const result = await catalog.api();
        items = result.items;
        for (const item of items) if (item.parent_entity_id == null) expanded.add(`entity:${item.entity_id}`);
        render();
    }
    function open(item=null, target=null) {
        if(busy)return;
        editing=item;parent=target;
        get('objectDirectoryNameInput').value=item?.name || '';
        get('cleanStatus').value=item?.activity_status || 'ACTIVE';
        get('cleanCategory').value=item?.category_id == null ? '' : String(item.category_id);
        get('objectDirectoryModalTitle').textContent=item ? 'Редактирование записи' : target ? 'Новый подобъект' : 'Добавить объект';
        get('objectDirectoryModalSave').textContent=item ? 'Сохранить' : 'Добавить';
        const type=modal.querySelector('select[disabled]');
        if(type)type.options[0].textContent=(item?.parent_entity_id != null || target) ? 'Подобъект' : 'Самостоятельный объект';
        error.hidden=true;modal.hidden=false;
    }
    async function archive(item) {
        if(busy || (!item.is_archived && !confirm(`Переместить «${item.name}» в архив?`)))return;
        busy=true;
        try {await catalog.archive(item); try{await load();}catch(_){alert('Изменения сохранены. Обновите страницу.');}}
        catch(e){alert(e.message);}finally{busy=false;}
    }
    get('addDirectoryObjectButton').onclick=()=>open();
    for(const id of ['objectDirectoryModalClose','objectDirectoryModalCancel'])get(id).onclick=()=>{if(!busy)modal.hidden=true;};
    get('objectDirectoryModalSave').onclick=async()=>{
        if(busy)return;
        busy=true;get('objectDirectoryModalSave').disabled=true;
        try {
            await catalog.save(editing,{name:get('objectDirectoryNameInput').value.trim(),
                activity_status:get('cleanStatus').value, category_id:get('cleanCategory').value ? Number(get('cleanCategory').value) : null},parent);
            modal.hidden=true;editing=null;
            try{await load();}catch(_){alert('Изменения сохранены. Обновите страницу.');}
        }catch(e){error.textContent=e.message;error.hidden=false;}
        finally{busy=false;get('objectDirectoryModalSave').disabled=false;}
    };
    for(const id of ['objectSearchInput','objectSort','objectStatusFilter'])get(id).addEventListener('input',render);
    for(const tab of doc.querySelectorAll('[data-object-view]'))tab.onclick=()=>{view=tab.dataset.objectView;render();};
    const categories=(await catalog.api('/categories')).items, select=get('cleanCategory');
    select.add(new Option('Без категории',''));
    const byId=new Map(categories.map(i=>[i.id,i]));
    for(const c of categories)select.add(new Option((c.parent_id ? `${byId.get(c.parent_id)?.name || ''} → ` : '')+c.name,String(c.id)));
    await load();
}
if(typeof module!=='undefined')module.exports={createCleanCatalog};
else startCleanWorkspace().catch(e=>alert(e.message));
