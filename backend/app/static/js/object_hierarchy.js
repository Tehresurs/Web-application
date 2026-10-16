/* Helpers for the existing construction objects directory. */
const hierarchyChoices = typeof ConstructionChoices !== 'undefined' ? ConstructionChoices : require('./construction_choices.js');
function objectMenuPosition(anchor, menu, viewport) {
    const gap = 5, margin = 8;
    const below = viewport.height - anchor.bottom - gap - margin;
    const above = anchor.top - gap - margin;
    const up = menu.height > below && above > below;
    const height = Math.min(menu.height, Math.max(0, up ? above : below));
    return {left: Math.max(margin, Math.min(anchor.right - menu.width, viewport.width - menu.width - margin)),
        top: Math.max(margin, up ? anchor.top - gap - height : anchor.bottom + gap),
        maxHeight: Math.max(0, up ? above : below), up};
}

function attachObjectMenu(menu, trigger, panel, doc) {
    // A native popover stays in the DOM for delegated actions, but paints in the top layer.
    if (!panel.showPopover) return;
    panel.setAttribute('popover', 'auto');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', 'Действия с записью');
    const win = doc.defaultView;
    const close = () => { if (panel.matches(':popover-open')) panel.hidePopover(); };
    const position = () => {
        if (!panel.matches(':popover-open')) return;
        const anchor = trigger.getBoundingClientRect();
        if (!trigger.isConnected || anchor.bottom < 0 || anchor.top > win.innerHeight) { close(); return; }
        panel.style.maxHeight = 'none';
        const rect = panel.getBoundingClientRect();
        const p = objectMenuPosition(anchor, rect, {width: win.innerWidth, height: win.innerHeight});
        Object.assign(panel.style, {left: `${p.left}px`, top: `${p.top}px`, maxHeight: `${p.maxHeight}px`});
        panel.dataset.direction = p.up ? 'up' : 'down';
    };
    trigger.addEventListener('click', event => {
        event.preventDefault();
        if (panel.matches(':popover-open')) { close(); return; }
        menu.open = true;
        panel.showPopover();
        trigger.setAttribute('aria-expanded', 'true');
        position();
    });
    panel.addEventListener('toggle', () => {
        const open = panel.matches(':popover-open');
        menu.open = open;
        trigger.setAttribute('aria-expanded', String(open));
        win.removeEventListener('resize', position);
        doc.removeEventListener('scroll', position, true);
        if (open) {
            win.addEventListener('resize', position);
            doc.addEventListener('scroll', position, true);
        }
    });
    panel.addEventListener('click', event => { if (event.target.closest('button')) close(); });
}
function objectHierarchyRows(objects, children, {query = "", sort = "asc", presence = "all", activity = "active"} = {}) {
    const normalize = value => String(value || "").toLocaleLowerCase("ru").replaceAll("ё", "е");
    const compare = (a, b) => a.name.localeCompare(b.name, "ru", {numeric: true, sensitivity: "base"}) || (a.id ?? a.entity_id) - (b.id ?? b.entity_id);
    query = normalize(query.trim());
    const grouped = new Map();
    for (const child of children) {
        const parentId = child.current_hierarchy?.parent_entity_id ?? child.parent_entity_id ?? child.object_id;
        if (!grouped.has(parentId)) grouped.set(parentId, []);
        grouped.get(parentId).push(child);
    }
    const rows = objects.map(item => {
        const entityId = item.current_hierarchy?.entity_id ?? item.entity_id ?? item.id;
        const all = (grouped.get(entityId) || []).slice().sort(compare);
        const eligible = all.filter(child => activity === "all" || child.is_active === (activity === "active"));
        const parentMatch = normalize(item.name).includes(query);
        const matches = eligible.filter(child => normalize(child.name).includes(query));
        return {item, total: all.length, active: all.filter(child => child.is_active).length,
            count: eligible.length, children: query && !parentMatch ? matches : eligible,
            matches: !query || parentMatch || matches.length > 0, forceOpen: Boolean(query && matches.length)};
    }).filter(row => row.matches && (presence === "all" || (presence === "with" ? row.count > 0 : row.count === 0)));
    return rows.sort((a, b) => (sort === "id" ? (a.item.id ?? a.item.entity_id) - (b.item.id ?? b.item.entity_id) : sort === "count" ? b.count - a.count :
        sort === "desc" ? -compare(a.item, b.item) : compare(a.item, b.item)) || compare(a.item, b.item));
}

function objectCatalogRows(objects, children, {view = "all", activity = "all", query = "", sort = "asc"} = {}) {
    const archivedChild = item => Boolean(item.is_archived || item.parent_is_archived);
    const matchesActivity = item => activity === "all" ||
        (activity === "active" ? item.is_active !== false && !["SUSPENDED", "COMPLETED"].includes(item.activity_status) :
            item.is_active === false || ["SUSPENDED", "COMPLETED"].includes(item.activity_status));
    const visibleChildren = children.filter(item => {
        const archived = archivedChild(item);
        if (view === "archived" ? !archived : archived) return false;
        return matchesActivity(item);
    });
    let visibleObjects = objects.filter(item => view === "archived" ? item.is_archived : !item.is_archived);
    let presence = "all";

    if (view === "standalone") {
        visibleChildren.length = 0;
    } else if (view === "children") {
        presence = "with";
        visibleObjects = objects.filter(item => !item.is_archived);
    } else if (view === "archived") {
        const parentsWithArchivedChildren = new Set(visibleChildren.map(item =>
            item.current_hierarchy?.parent_entity_id ?? item.parent_entity_id ?? item.object_id));
        visibleObjects = objects.filter(item => item.is_archived || parentsWithArchivedChildren.has(
            item.current_hierarchy?.entity_id ?? item.entity_id ?? item.id));
    } else if (view !== "all") {
        return [];
    }

    if (view !== "archived" && activity !== "all") {
        visibleObjects = visibleObjects.filter(matchesActivity);
    }
    return objectHierarchyRows(visibleObjects, visibleChildren, {
        query, sort, presence, activity: "all",
    });
}

function renderObjectHierarchy(container, rows, {expanded, onAdd, onEdit, onPromote, onMakeStandalone, onRootEdit, onArchive, activity = "active", testMode = false, parents = [], selectedId = null, onSelect, document: doc = document}) {
    const element = (tag, text, className) => {
        const node = doc.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    };
    const icon = (name, className) => {
        const node = typeof uiIcon === "function" ? uiIcon(name) : element("span");
        if (node.classList) node.classList.add(className);
        else node.className = `${node.className || ""} ${className}`.trim();
        return node;
    };
    const statusBadge = item => {
        if (item.is_archived || item.parent_is_archived) {
            return {label: item.is_archived ? "В архиве" : "Родитель в архиве", tone: "badge-neutral ui-badge-muted"};
        }
        if (item.activity_status === "SUSPENDED") return {label: "Приостановлен", tone: "badge-orange"};
        if (item.activity_status === "COMPLETED") return {label: "Завершён", tone: "badge-neutral"};
        if (item.is_active === false) return {label: "Неактивен", tone: "badge-neutral"};
        return {label: "Действующий", tone: "badge-green"};
    };
    const actionMenu = actions => {
        const menu = element("details", undefined, "object-action-menu");
        const trigger = element("summary", testMode ? "⋯" : "Действия", "ui-button");
        menu.append(trigger);
        const items = element("div", undefined, "object-action-menu-items ui-card");
        for (const [label, className, callback, id] of actions) {
            const button = element("button", label, "ui-button object-action-item " + className);
            button.type = "button";
            if (id != null) button.dataset.id = String(id);
            button.addEventListener("click", callback);
            items.append(button);
        }
        menu.append(items);
        if (testMode) attachObjectMenu(menu, trigger, items, doc);
        return menu;
    };
    container.replaceChildren();
    if (!rows.length) { container.append(element("div", "Объекты не найдены", "category-empty")); return; }
    if (testMode) {
        const table = element("table", undefined, "ui-table object-catalog-table");
        const head = element("thead");
        const header = element("tr");
        for (const label of ["Наименование", "Тип", "Статус", "Родительский объект", "Код", "Действия"]) {
            const cell = element("th", label);
            cell.scope = "col";
            header.append(cell);
        }
        head.append(header);
        table.append(head);
        const body = element("tbody");
        const parentByEntity = new Map(parents.map(parent => [
            String(parent.current_hierarchy?.entity_id ?? parent.entity_id ?? parent.id), parent,
        ]));
        const statusFor = item => {
            if (item.is_archived || item.parent_is_archived) return {label: "Архив", tone: "badge-neutral ui-badge-muted"};
            if (item.activity_status === "SUSPENDED") return {label: "Приостановлен", tone: "badge-orange"};
            if (item.activity_status === "COMPLETED") return {label: "Завершён", tone: "badge-neutral"};
            if (item.is_active === false) return {label: "Неактивен", tone: "badge-neutral"};
            return {label: "Действующий", tone: "badge-green"};
        };
        const codeFor = item => item.code ?? item.object_code ?? item.code_value ?? item.construction_code ?? "";
        const recordKey = item => item.id ?? `entity:${item.entity_id ?? item.current_hierarchy?.entity_id}`;
        const toggle = (item, options = {}) => {
            if (options.child) {
                if (onEdit) onEdit(item);
                return;
            }
            const isExpanded = expanded.has(recordKey(item));
            if (isExpanded) expanded.delete(recordKey(item));
            else expanded.add(recordKey(item));
            if (onSelect) onSelect(recordKey(item));
            else {
                renderObjectHierarchy(container, rows, {expanded, onAdd, onEdit, onPromote, onMakeStandalone,
                    activity, testMode, parents, selectedId: recordKey(item), onSelect, document: doc});
            }
        };
        const appendRecord = (item, {child = false, parentName = "", hasChildren = false, parentId = null} = {}) => {
            const entityId = item.current_hierarchy?.entity_id ?? item.entity_id ?? item.id;
            const row = element("tr", undefined, child ? "object-catalog-child-row" : "object-catalog-root-row");
            row.dataset.recordId = String(recordKey(item));
            row.dataset.entityId = String(entityId);
            if (child) row.dataset.parentId = String(parentId ?? "");
            row.setAttribute("aria-selected", String(String(selectedId) === String(recordKey(item))));
            row.addEventListener("click", event => {
                if (event.target.closest?.(".object-action-menu")) return;
                onSelect?.(recordKey(item));
            });

            const nameCell = element("td", undefined, "object-catalog-name-cell");
            if (child) {
                nameCell.append(element("span", "↳", "object-catalog-branch"));
            } else {
                const disclosure = element("button", hasChildren ? (expanded.has(recordKey(item)) ? "⌄" : "›") : "", "object-tree-disclosure");
                disclosure.type = "button";
                disclosure.disabled = !hasChildren;
                disclosure.setAttribute("aria-expanded", String(expanded.has(recordKey(item))));
                disclosure.setAttribute("aria-label", `${expanded.has(recordKey(item)) ? "Свернуть" : "Раскрыть"} подобъекты: ${item.name}`);
                disclosure.addEventListener("click", event => {
                    event.stopPropagation();
                    toggle(item);
                });
                nameCell.append(disclosure, icon("object", "object-catalog-icon"));
            }
            const name = element("span", item.name, "object-catalog-name");
            name.title = item.name;
            nameCell.append(name);
            row.append(nameCell);
            row.append(element("td", child ? "Подобъект" : "Самостоятельный объект", "object-catalog-type"));
            const status = statusFor(item);
            const statusCell = element("td");
            statusCell.append(element("span", status.label, `ui-badge ${status.tone} object-status-badge`));
            row.append(statusCell);
            row.append(element("td", child ? (parentName || "—") : "—", "object-catalog-parent"));
            row.append(element("td", codeFor(item) || "—", "object-catalog-code"));

            const actions = [];
            if (child) {
                actions.push(["Редактировать", "edit-subobject-directory", () => onEdit(item)]);
                if (onMakeStandalone && !item.is_archived && !item.parent_is_archived) actions.push(["Сделать самостоятельным объектом", "make-standalone-preview", () => onMakeStandalone(item)]);
                if (item.is_archived || !item.parent_is_archived) actions.push([item.is_archived ? "Восстановить из архива" : "В архив",
                    "archive-subobject-directory", () => onArchive?.(item), item.entity_id != null ? `entity:${item.entity_id}` : item.id]);
            } else {
                actions.push(["Редактировать", "edit-object-directory", () => onRootEdit?.(item), item.entity_id != null ? `entity:${item.entity_id}` : item.id]);
                if (!item.is_archived) actions.push(["Создать подобъект", "add-subobject-directory", () => onAdd(item)]);
                if (onPromote && !item.is_archived) actions.push(["Преобразовать в подобъект", "promote-preview", () => onPromote(item)]);
                actions.push([item.is_archived ? "Восстановить из архива" : "В архив",
                    "archive-object-directory", () => onArchive?.(item), item.entity_id != null ? `entity:${item.entity_id}` : item.id]);
            }
            const actionsCell = element("td", undefined, "object-catalog-actions");
            actionsCell.append(actionMenu(actions));
            row.append(actionsCell);
            body.append(row);

            if (!child && hasChildren && expanded.has(recordKey(item))) {
                const childList = rows.find(candidate => String(recordKey(candidate.item)) === String(recordKey(item)))?.children || [];
                for (const subobject of childList) {
                    const subParentId = subobject.current_hierarchy?.parent_entity_id ?? subobject.parent_entity_id ?? subobject.object_id;
                    const parent = parentByEntity.get(String(subParentId));
                    appendRecord(subobject, {child: true, parentName: subobject.current_hierarchy?.parent?.name ??
                        subobject.parent_name ?? subobject.object_name ?? parent?.name ?? "", parentId: subParentId});
                }
            }
        };
        for (const item of rows) appendRecord(item.item, {
            hasChildren: item.children.length > 0,
        });
        table.append(body);
        container.append(table);
        return;
    }
    for (const row of rows) {
        const details = element("details", undefined, `object-tree-parent${testMode ? " ui-card" : ""}`);
        details.dataset.objectId = row.item.id;
        details.open = row.forceOpen || expanded.has(row.item.id);
        details.addEventListener("toggle", () => {
            if (details.open) expanded.add(row.item.id); else expanded.delete(row.item.id);
            if (testMode && summary.setAttribute) summary.setAttribute("aria-selected", String(details.open));
        });
        const summary = element("summary");
        if (testMode) {
            const badge = statusBadge(row.item);
            if (summary.setAttribute) summary.setAttribute("aria-selected", String(details.open));
            summary.append(icon("object", "section-icon"), element("strong", row.item.name),
                element("small", `Подобъектов: ${row.total}`),
                element("span", badge.label, `ui-badge ${badge.tone} object-status-badge`));
        } else {
            summary.append(element("strong", row.item.name), element("small", activity === "active"
                ? `Подобъектов: ${row.active}` : `Подобъектов: ${row.total} · Активных: ${row.active}`));
        }
        details.append(summary);
        const list = element("div", undefined, "object-tree-children");
        if (!row.children.length) list.append(element("p", "Нет подобъектов для выбранного фильтра", "category-empty"));
        for (const child of row.children) {
            const line = element("div", undefined, "object-tree-child");
            line.dataset.subobjectId = child.id;
            const name = element("div");
            name.append(element("strong", child.name));
            if (testMode) {
                const badge = statusBadge(child);
                name.append(element("span", badge.label, `ui-badge ${badge.tone} object-status-badge`));
            } else {
                name.append(element("small", child.is_active ? "Активен" : "Неактивен"));
            }
            if (testMode) {
                const actions = [
                    ["Редактировать", "edit-subobject-directory", () => onEdit(child)],
                ];
                if (onMakeStandalone) actions.push(["Сделать самостоятельным объектом", "make-standalone-preview", () => onMakeStandalone(child)]);
                if (!child.parent_is_archived) {
                    actions.push([child.is_archived ? "Восстановить из архива" : "В архив",
                        "archive-subobject-directory", () => {}, child.id]);
                }
                line.append(name, actionMenu(actions));
            } else {
                const edit = element("button", "Редактировать", "secondary-button");
                edit.type = "button";
                edit.addEventListener("click", () => onEdit(child));
                line.append(name, edit);
            }
            if (!testMode && onMakeStandalone) {
                const standalone = element("button", "Сделать самостоятельным объектом", "ui-button");
                standalone.type = "button";
                standalone.addEventListener("click", () => onMakeStandalone(child));
                line.append(standalone);
            }
            list.append(line);
        }
        if (testMode) {
            const actions = [
                ["Создать подобъект", "add-subobject-directory", () => onAdd(row.item)],
                ["Редактировать", "edit-object-directory", () => {}, row.item.id],
            ];
            if (onPromote) actions.push(["Преобразовать в подобъект", "promote-preview", () => onPromote(row.item)]);
            actions.push([row.item.is_archived ? "Восстановить из архива" : "В архив",
                "archive-object-directory", () => {}, row.item.id]);
            details.append(actionMenu(actions));
        } else {
            const actions = element("div", undefined, "object-tree-actions");
            const add = element("button", "+ Добавить подобъект", "secondary-button");
            add.type = "button"; add.addEventListener("click", () => onAdd(row.item));
            const edit = element("button", "Редактировать объект", "secondary-button edit-object-directory");
            edit.type = "button"; edit.dataset.id = row.item.id;
            const remove = element("button", "В архив", "category-icon-button danger delete-object-directory");
            remove.type = "button"; remove.dataset.id = row.item.id;
            actions.append(add, edit, remove);
            if (onPromote) {
                const promote = element("button", "Преобразовать в подобъект", "ui-button");
                promote.type = "button";
                promote.addEventListener("click", () => onPromote(row.item));
                actions.append(promote);
            }
            details.append(list, actions);
        }
        if (testMode) details.append(list);
        container.append(details);
    }
}

function createSubobjectDirectoryEditor({document: doc = document, getObjects, onSaved, request = fetch}) {
    const get = id => doc.getElementById(id);
    const modal = get("subobjectDirectoryModal"), name = get("subobjectDirectoryName"), parent = get("subobjectDirectoryParent");
    const code = get("subobjectDirectoryCode");
    const active = get("subobjectDirectoryActive"), save = get("subobjectDirectorySave"), error = get("subobjectDirectoryError");
    const confirmation = get("subobjectDirectoryConfirmation");
    let editing = null, originalParent = null, originalParentValue = '', parentChoices = [], plan = null, busy = false;
    function resetPlan() { plan = null; confirmation.hidden = true; save.textContent = editing ? "Сохранить" : "Добавить"; }
    function close() { if (!busy) { modal.hidden = true; resetPlan(); } }
    function open(object, child = null) {
        editing = child; originalParent = child?.current_hierarchy?.parent_entity_id ?? child?.object_id ?? object?.entity_id ?? object?.id ?? null;
        name.value = child?.name || "";
        if (code) code.value = child?.code ?? child?.object_code ?? child?.code_value ?? child?.construction_code ?? "";
        parent.replaceChildren();
        const currentParent = child?.current_hierarchy?.parent || object ||
            getObjects().find(item => item.id === originalParent) || {id: originalParent, name: child?.object_name};
        const choices = hierarchyChoices.options(getObjects(), child ? currentParent : null,
            {parentsOnly: true, excluded: child?.entity_id ? child : null});
        parentChoices = choices.rows;
        originalParentValue = child ? choices.selected : hierarchyChoices.value(object);
        for (const row of parentChoices) {
            const option = doc.createElement("option"); option.value = row.value; option.textContent = row.label;
            option.disabled = Boolean(row.historical); parent.append(option);
        }
        parent.value = parentChoices.some(row => row.value === originalParentValue) ? originalParentValue : '';
        parent.disabled = !child;
        active.value = child?.is_active === false ? "false" : "true";
        get("subobjectDirectoryActiveLabel").hidden = !child;
        get("subobjectDirectoryTitle").textContent = child ? "Редактирование подобъекта" : "Новый подобъект";
        error.hidden = true; resetPlan(); modal.hidden = false; name.focus();
    }
    async function api(url, method, payload) {
        const response = await request(url, {method, headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error("Не удалось сохранить подобъект. Повторите попытку."); }
        if (!response.ok) {
            const message = response.status === 409 ? (data.message?.includes("названием")
                ? "Такой подобъект уже существует у этого объекта." : data.message || "Такой подобъект уже существует у этого объекта.")
                : response.status === 404 ? "Объект или подобъект больше не существует. Обновите список."
                : response.status === 400 || response.status === 422 ? "Проверьте название и выбранный родительский объект."
                : "Не удалось сохранить подобъект. Повторите попытку.";
            throw new Error(message);
        }
        return data;
    }
    async function submit(event) {
        event?.preventDefault();
        if (busy) return;
        if (!name.value.trim()) { error.textContent = "Введите название подобъекта"; error.hidden = false; return; }
        busy = true; save.disabled = true; name.disabled = true; parent.disabled = true; active.disabled = true; error.hidden = true;
        const payload = {name:name.value.trim(),is_active:active.value === "true"};
        const chosen = parentChoices.find(row => row.value === parent.value)?.item;
        const objectId = hierarchyChoices.hierarchy(chosen).legacy_object_id ?? (chosen?.entity_id ? null : chosen?.id);
        try {
            let result;
            if (!parent.value) throw new Error('Выберите действующий самостоятельный родительский объект');
            if (!editing) result = await api("/api/subobjects", "POST", {...hierarchyChoices.reference(parent.value, true),name:payload.name});
            else if (parent.value === originalParentValue) result = await api(editing.entity_id != null ? `/api/subobjects/${editing.entity_id}?id_type=entity` : `/api/subobjects/${editing.id}`, "PATCH", payload);
            else {
                if (objectId == null || editing.id == null) throw new Error('Перенос к выбранной сущности пока недоступен: требуется адаптация API переноса к entity_id');
                if (!plan) {
                    plan = (await api(`/api/subobjects/${editing.id}/move/check`, "POST", {...payload,object_id:objectId})).item;
                    if (plan.requires_confirmation) {
                        confirmation.textContent = `ПОДОБЪЕКТ ИСПОЛЬЗУЕТСЯ В ЖУРНАЛЕ\n«${editing.name}»\nСтарый объект: ${plan.old_object_name}\nНовый объект: ${plan.object_name}\nСвязанных записей Журнала: ${plan.linked_facts}\nПри переносе связанные записи будут приведены в соответствие новому родителю.`;
                        if (plan.missing_assignments) confirmation.textContent += `\nПосле переноса обнаружены записи контроля инженеров, для которых отсутствует назначение на новый основной объект: ${plan.missing_assignments}. Назначения автоматически не создаются.`;
                        confirmation.hidden = false; save.textContent = "Перенести"; return;
                    }
                }
                result = await api(`/api/subobjects/${editing.id}/move`, "PATCH", {...payload,object_id:objectId,confirmation_token:plan.confirmation_token});
            }
            try { await onSaved(result.item, originalParent); modal.hidden = true; }
            catch (_) {
                editing = result.item; originalParent = result.item.object_id; resetPlan();
                error.textContent = "Изменения сохранены. Не удалось обновить список — обновите страницу."; error.hidden = false;
            }
        } catch (e) { resetPlan(); error.textContent = e.message; error.hidden = false; }
        finally { busy = false; save.disabled = false; name.disabled = false; parent.disabled = !editing; active.disabled = false; }
    }
    for (const field of [name, parent, active]) field.addEventListener("input", resetPlan);
    get("subobjectDirectoryForm").addEventListener("submit", submit);
    get("subobjectDirectoryCancel").addEventListener("click", close);
    get("subobjectDirectoryClose").addEventListener("click", close);
    modal.addEventListener("click", event => { if (event.target === modal) close(); });
    return {open, close};
}

if (typeof module !== "undefined") module.exports = {objectMenuPosition, objectHierarchyRows, objectCatalogRows, renderObjectHierarchy, createSubobjectDirectoryEditor};
