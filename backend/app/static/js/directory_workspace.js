/* Presentation adapters only. Existing delegated CRUD handlers stay on containers. */
const directorySelection={crew:null,object:null};
const directoryControls={};
function directoryNode(tag,text,className){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;}
function directoryWorkspace(container,items,kind,label,render){
    const controlIds=kind==='crew'?['crewSearchInput','addCrewButton']:['objectSearchInput','addDirectoryObjectButton'];
    const controls=directoryControls[kind]||(directoryControls[kind]=controlIds.map(id=>document.getElementById(id)).filter(Boolean));
    const focused=document.activeElement;
    container.replaceChildren();container.classList.add('directory-workspace');
    if(!items.some(i=>i.id===directorySelection[kind]))directorySelection[kind]=items[0]?.id??null;
    const list=directoryNode('div',null,'ui-card directory-roster'),card=directoryNode('article',null,'ui-card directory-profile');
    container.append(list,card);
    for(const control of controls)list.append(control);
    if(controls.includes(focused))focused.focus({preventScroll:true});
    if(!items.length){list.append(directoryNode('p','Ничего не найдено','ui-empty'));card.append(directoryNode('p','Измените поиск или добавьте запись','ui-empty'));return;}
    for(const item of items){const button=directoryNode('button',label(item),'directory-choice');button.type='button';button.dataset.recordId=item.id;button.classList.toggle('selected',item.id===directorySelection[kind]);button.setAttribute('aria-pressed',String(item.id===directorySelection[kind]));button.onclick=()=>{directorySelection[kind]=item.id;directoryWorkspace(container,items,kind,label,render);};list.append(button);}
    render(card,items.find(i=>i.id===directorySelection[kind]));
}
function renderCrewWorkspace(container,items){
    directoryWorkspace(container,items,'crew',item=>[item.name||'Экипаж',item.driver_full_name,item.vehicle_plate].filter(Boolean).join(' · '),(card,item)=>{
        const h=directoryNode('h2',item.name||'Карточка экипажа');if(typeof uiIcon==='function')h.prepend(uiIcon('truck'));card.append(h);
        const dl=directoryNode('dl',null,'ui-fields');
        for(const [label,key] of [['Водитель','driver_full_name'],['Телефон','driver_phone'],['Марка автомобиля','vehicle_make'],['Государственный номер','vehicle_plate']])dl.append(directoryNode('dt',label),directoryNode('dd',item[key]||'—'));
        card.append(dl);const actions=directoryNode('div',null,'directory-actions');
        for(const [text,cls] of [['Редактировать','edit-crew'],['Удалить','delete-crew']]){const b=directoryNode('button',text,'ui-button '+cls);b.type='button';b.dataset.id=item.id;actions.append(b);}card.append(actions);
        renderCrewMembers(card,item);
    });
}
function renderObjectWorkspace(container,rows,options){
    directoryWorkspace(container,rows.map(r=>({...r.item,row:r})),'object',item=>item.name,(card,item)=>{
        // Same hierarchy renderer and editor callbacks, only one selected parent.
        renderObjectHierarchy(card,[item.row],{...options,expanded:new Set([item.id])});
        const details=card.querySelector('details');if(details)details.open=true;
        card.querySelector('.delete-object-directory')?.remove();
        objectArchiveControls(card,item,'objects');
        for(const child of item.row.children){const host=card.querySelector(`[data-subobject-id="${child.id}"]`);if(host)objectArchiveControls(host,child,'subobjects');}
        card.append(directoryNode('p','Категории и ПО задаются в закреплениях сотрудников, а не в карточке объекта.','ui-muted'));
    });
}
