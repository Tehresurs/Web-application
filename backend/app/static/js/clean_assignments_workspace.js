function createCleanAssignmentsClient(request = fetch) {
    const base = '/api/clean-construction-entities';

    async function api(path, method = 'GET', payload) {
        const response = await request(base + path, {
            method,
            headers: {'Content-Type': 'application/json'},
            body: payload === undefined ? undefined : JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            throw Error(typeof result.detail === 'string' ? result.detail : result.message || 'Не удалось выполнить операцию');
        }
        return result;
    }

    return {
        async dictionaries() {
            const [employees, poTypes, categories, entities] = await Promise.all([
                api('/employees?archive=active'),
                api('/po-types'),
                api('/categories'),
                api('?archive=active')
            ]);
            return {
                employees: employees.items,
                poTypes: poTypes.items,
                categories: categories.items,
                entities: entities.items.filter(item => item.is_active && !item.is_archived &&
                    !item.parent_is_archived && item.parent_is_active !== false)
            };
        },
        assignments(employeeId) {
            return api(`/employees/${employeeId}/assignments`);
        },
        save(employeeId, assignment, values) {
            const path = `/employees/${employeeId}/assignments${assignment ? `/${assignment.id}` : ''}`;
            return api(path, assignment ? 'PATCH' : 'POST', values);
        },
        remove(employeeId, assignmentId) {
            return api(`/employees/${employeeId}/assignments/${assignmentId}`, 'DELETE');
        }
    };
}

function cleanCategoryLabel(category, categoriesById) {
    const path = [category.name];
    const seen = new Set([category.id]);
    let current = category;
    while (current.parent_id != null && !seen.has(current.parent_id)) {
        seen.add(current.parent_id);
        current = categoriesById.get(current.parent_id);
        if (!current) break;
        path.push(current.name);
    }
    return path.reverse().join(' → ');
}

async function startCleanAssignmentsWorkspace(doc = document, request = fetch) {
    const client = createCleanAssignmentsClient(request);
    const get = id => doc.getElementById(id);
    const employeeSelect = get('cleanAssignmentEmployee');
    const entitySelect = get('cleanAssignmentEntity');
    const poSelect = get('cleanAssignmentPo');
    const categorySelect = get('cleanAssignmentCategory');
    const list = get('cleanAssignmentList');
    const editor = get('cleanAssignmentEditor');
    const error = get('cleanAssignmentError');
    let assignments = [];
    let editing = null;
    let dictionaries;

    function showError(message) {
        error.textContent = message;
        error.hidden = false;
    }

    function renderAssignments() {
        list.replaceChildren();
        if (!assignments.length) {
            const empty = doc.createElement('div');
            empty.className = 'assignment-empty';
            empty.textContent = 'Назначений пока нет';
            list.append(empty);
            get('cleanAssignmentCount').textContent = 'Объектов: 0';
            return;
        }
        for (const item of assignments) {
            const row = doc.createElement('div');
            row.className = 'assignment-row';
            row.dataset.assignmentId = String(item.id);
            const main = doc.createElement('div');
            main.className = 'assignment-main';
            const entity = doc.createElement('strong');
            entity.className = 'assignment-object';
            entity.textContent = item.parent_name ? `${item.parent_name} → ${item.object_name}` : item.object_name;
            const po = doc.createElement('span');
            po.className = 'assignment-po';
            po.textContent = `ПО: ${item.po_name}`;
            const category = doc.createElement('span');
            category.className = 'assignment-category';
            category.textContent = `Категория: ${item.category_name}`;
            main.append(entity, po, category);
            const actions = doc.createElement('div');
            actions.className = 'category-actions';
            const edit = doc.createElement('button');
            edit.type = 'button';
            edit.className = 'category-icon-button clean-assignment-edit';
            edit.textContent = 'Изменить';
            edit.dataset.id = String(item.id);
            const remove = doc.createElement('button');
            remove.type = 'button';
            remove.className = 'category-icon-button danger clean-assignment-delete';
            remove.textContent = 'Удалить';
            remove.dataset.id = String(item.id);
            actions.append(edit, remove);
            row.append(main, actions);
            list.append(row);
        }
        get('cleanAssignmentCount').textContent = `Объектов: ${new Set(assignments.map(item => item.entity_id)).size}`;
    }

    async function loadAssignments() {
        const employeeId = employeeSelect.value;
        if (!employeeId) {
            assignments = [];
            renderAssignments();
            return;
        }
        const result = await client.assignments(employeeId);
        assignments = result.items;
        renderAssignments();
    }

    function fillChoices(assignment = null) {
        entitySelect.replaceChildren(new Option('Выберите объект', ''));
        const entities = [...dictionaries.entities];
        const current = assignment?.current_hierarchy;
        if (current && !entities.some(item => item.entity_id === current.entity_id)) {
            entities.push({...current, parent_is_archived: Boolean(current.parent?.is_archived)});
        }
        entities.sort((a, b) => a.name.localeCompare(b.name, 'ru') || a.entity_id - b.entity_id);
        for (const item of entities) {
            const parentName = item.parent?.name || item.parent_name;
            const option = new Option(parentName ? `${parentName} → ${item.name}` : item.name, String(item.entity_id));
            entitySelect.add(option);
        }

        poSelect.replaceChildren(new Option('Выберите ПО', ''));
        for (const item of dictionaries.poTypes) poSelect.add(new Option(item.name, String(item.id)));

        categorySelect.replaceChildren(new Option('Выберите категорию', ''));
        const categoriesById = new Map(dictionaries.categories.map(item => [item.id, item]));
        for (const item of dictionaries.categories) {
            categorySelect.add(new Option(cleanCategoryLabel(item, categoriesById), String(item.id)));
        }
        entitySelect.value = assignment ? String(assignment.entity_id) : '';
        poSelect.value = assignment ? String(assignment.po_id) : '';
        categorySelect.value = assignment ? String(assignment.category_id) : '';
    }

    async function openEditor(assignment = null) {
        try {
            dictionaries = await client.dictionaries();
            fillChoices(assignment);
            editing = assignment;
            get('cleanAssignmentSave').textContent = assignment ? 'Сохранить' : 'Добавить';
            error.hidden = true;
            editor.hidden = false;
        } catch (cause) {
            showError(cause.message);
        }
    }

    function closeEditor() {
        editor.hidden = true;
        editing = null;
        error.hidden = true;
    }

    async function loadDictionaries() {
        dictionaries = await client.dictionaries();
        employeeSelect.replaceChildren(new Option('Выберите сотрудника', ''));
        for (const employee of dictionaries.employees) {
            employeeSelect.add(new Option(employee.full_name, String(employee.id)));
        }
        if (dictionaries.employees.length) {
            employeeSelect.value = String(dictionaries.employees[0].id);
            await loadAssignments();
        }
    }

    employeeSelect.addEventListener('change', () => loadAssignments().catch(cause => showError(cause.message)));
    get('cleanAssignmentAdd').addEventListener('click', () => {
        if (!employeeSelect.value) {
            showError('Выберите сотрудника');
            return;
        }
        openEditor();
    });
    get('cleanAssignmentCancel').addEventListener('click', closeEditor);
    get('cleanAssignmentSave').addEventListener('click', async event => {
        const button = event.currentTarget;
        if (!employeeSelect.value || !entitySelect.value || !poSelect.value || !categorySelect.value) {
            showError('Выберите сотрудника, объект, ПО и категорию');
            return;
        }
        button.disabled = true;
        error.hidden = true;
        try {
            await client.save(employeeSelect.value, editing, {
                entity_id: Number(entitySelect.value),
                po_id: Number(poSelect.value),
                category_id: Number(categorySelect.value)
            });
            closeEditor();
            await loadAssignments();
        } catch (cause) {
            showError(cause.message);
        } finally {
            button.disabled = false;
        }
    });
    list.addEventListener('click', async event => {
        const edit = event.target.closest('.clean-assignment-edit');
        const remove = event.target.closest('.clean-assignment-delete');
        const id = Number((edit || remove)?.dataset.id);
        const assignment = assignments.find(item => item.id === id);
        if (edit && assignment) {
            await openEditor(assignment);
            return;
        }
        if (remove && assignment && confirm(`Удалить закрепление «${assignment.object_name}»?`)) {
            try {
                await client.remove(employeeSelect.value, assignment.id);
                await loadAssignments();
            } catch (cause) {
                showError(cause.message);
            }
        }
    });
    await loadDictionaries();
    return {client, loadAssignments};
}

if (typeof module !== 'undefined') module.exports = {createCleanAssignmentsClient, cleanCategoryLabel};
else startCleanAssignmentsWorkspace().catch(error => alert(error.message));
