/* Helpers for the existing construction objects directory. */
function objectHierarchyRows(objects, children, {query = "", sort = "asc", presence = "all", activity = "active"} = {}) {
    const normalize = value => String(value || "").toLocaleLowerCase("ru").replaceAll("ё", "е");
    const compare = (a, b) => a.name.localeCompare(b.name, "ru", {numeric: true, sensitivity: "base"}) || a.id - b.id;
    query = normalize(query.trim());
    const grouped = new Map();
    for (const child of children) {
        if (!grouped.has(child.object_id)) grouped.set(child.object_id, []);
        grouped.get(child.object_id).push(child);
    }
    const rows = objects.map(item => {
        const all = (grouped.get(item.id) || []).slice().sort(compare);
        const eligible = all.filter(child => activity === "all" || child.is_active === (activity === "active"));
        const parentMatch = normalize(item.name).includes(query);
        const matches = eligible.filter(child => normalize(child.name).includes(query));
        return {item, total: all.length, active: all.filter(child => child.is_active).length,
            count: eligible.length, children: query && !parentMatch ? matches : eligible,
            matches: !query || parentMatch || matches.length > 0, forceOpen: Boolean(query && matches.length)};
    }).filter(row => row.matches && (presence === "all" || (presence === "with" ? row.count > 0 : row.count === 0)));
    return rows.sort((a, b) => (sort === "id" ? a.item.id - b.item.id : sort === "count" ? b.count - a.count :
        sort === "desc" ? -compare(a.item, b.item) : compare(a.item, b.item)) || compare(a.item, b.item));
}

function renderObjectHierarchy(container, rows, {expanded, onAdd, onEdit, activity = "active", document: doc = document}) {
    const element = (tag, text, className) => {
        const node = doc.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    };
    container.replaceChildren();
    if (!rows.length) { container.append(element("div", "Объекты не найдены", "category-empty")); return; }
    for (const row of rows) {
        const details = element("details", undefined, "object-tree-parent");
        details.dataset.objectId = row.item.id;
        details.open = row.forceOpen || expanded.has(row.item.id);
        details.addEventListener("toggle", () => {
            if (details.open) expanded.add(row.item.id); else expanded.delete(row.item.id);
        });
        const summary = element("summary");
        summary.append(element("strong", row.item.name), element("small", activity === "active"
            ? `Подобъектов: ${row.active}` : `Подобъектов: ${row.total} · Активных: ${row.active}`));
        details.append(summary);
        const list = element("div", undefined, "object-tree-children");
        if (!row.children.length) list.append(element("p", "Нет подобъектов для выбранного фильтра", "category-empty"));
        for (const child of row.children) {
            const line = element("div", undefined, "object-tree-child");
            line.dataset.subobjectId = child.id;
            const name = element("div");
            name.append(element("strong", child.name), element("small", child.is_active ? "Активен" : "Неактивен"));
            const edit = element("button", "Редактировать", "secondary-button");
            edit.type = "button";
            edit.addEventListener("click", () => onEdit(child));
            line.append(name, edit); list.append(line);
        }
        const actions = element("div", undefined, "object-tree-actions");
        const add = element("button", "+ Добавить подобъект", "secondary-button");
        add.type = "button"; add.addEventListener("click", () => onAdd(row.item));
        const edit = element("button", "Редактировать объект", "secondary-button edit-object-directory");
        edit.type = "button"; edit.dataset.id = row.item.id;
        const remove = element("button", "Удалить объект", "category-icon-button danger delete-object-directory");
        remove.type = "button"; remove.dataset.id = row.item.id;
        actions.append(add, edit, remove);
        details.append(list, actions); container.append(details);
    }
}

function createSubobjectDirectoryEditor({document: doc = document, getObjects, onSaved, request = fetch}) {
    const get = id => doc.getElementById(id);
    const modal = get("subobjectDirectoryModal"), name = get("subobjectDirectoryName"), parent = get("subobjectDirectoryParent");
    const active = get("subobjectDirectoryActive"), save = get("subobjectDirectorySave"), error = get("subobjectDirectoryError");
    const confirmation = get("subobjectDirectoryConfirmation");
    let editing = null, originalParent = null, plan = null, busy = false;
    function resetPlan() { plan = null; confirmation.hidden = true; save.textContent = editing ? "Сохранить" : "Добавить"; }
    function close() { if (!busy) { modal.hidden = true; resetPlan(); } }
    function open(object, child = null) {
        editing = child; originalParent = child?.object_id ?? object.id;
        name.value = child?.name || "";
        parent.replaceChildren();
        for (const item of getObjects().slice().sort((a,b) => a.name.localeCompare(b.name, "ru"))) {
            const option = doc.createElement("option"); option.value = String(item.id); option.textContent = item.name; parent.append(option);
        }
        parent.value = String(originalParent); parent.disabled = !child;
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
        const objectId = Number(parent.value);
        try {
            let result;
            if (!editing) result = await api("/api/subobjects", "POST", {object_id:originalParent,name:payload.name});
            else if (objectId === originalParent) result = await api(`/api/subobjects/${editing.id}`, "PATCH", payload);
            else {
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

if (typeof module !== "undefined") module.exports = {objectHierarchyRows, renderObjectHierarchy, createSubobjectDirectoryEditor};
