function journalQuery(from, to, view, employee = "", object = "", includeSubobjects = true, subcontractor = "") {
    if (!from || !to || from > to) throw new Error("Укажите корректный период: начало не позже окончания.");
    const query = new URLSearchParams({date_from: from, date_to: to, view});
    if (employee) {
        if (!/^[1-9]\d*$/.test(String(employee))) throw new Error("Выберите инженера из списка.");
        query.set("employee_id", employee);
    }
    if (object) {
        // Numeric values remain supported for existing callers; the UI uses typed keys.
        const match = String(object).match(/^(?:(object|subobject):)?([1-9]\d*)$/);
        if (!match) throw new Error("Выберите объект или подобъект из списка.");
        const child = match[1] === "subobject";
        query.set(child ? "subobject_id" : "object_id", match[2]);
        if (!child) query.set("include_subobjects", String(includeSubobjects));
    }
    if (subcontractor) {
        if (!/^[1-9]\d*$/.test(String(subcontractor))) throw new Error("Выберите субподрядчика из списка.");
        query.set("subcontractor_id", subcontractor);
    }
    return query.toString();
}

function journalItemLabel(item) {
    return item.control_item_type === "subobject"
        ? `ПОДОБЪЕКТ: ${item.control_item_name} ↳ ${item.object_name}`
        : `ОБЪЕКТ: ${item.control_item_name}`;
}

function journalHistoryFilters(current, kind, item) {
    // Drilling into an engineer retains the selected position, period and inclusion mode.
    return kind === "employee" ? {...current, employee: String(item.employee_id), view: "employee"}
        : {...current, object: item.control_item_key, view: "object"};
}

function journalOptions(items, id, label) {
    return [...new Map(items.map(item => [String(item[id]), item[label]])).entries()]
        .sort((a, b) => a[1].localeCompare(b[1], "ru"));
}

function initJournal() {
    const get = id => document.getElementById(id);
    const from = get("journalFrom"), to = get("journalTo"), view = get("journalView");
    const employee = get("journalEmployee"), object = get("journalObject");
    const include = get("journalIncludeSubobjects");
    const subcontractor = get("journalSubcontractor");
    const message = get("journalMessage"), groups = get("journalGroups"), summary = get("journalSummary");
    let requestNumber = 0;
    let controller;
    const displayDate = value => value.split("-").reverse().join(".");
    const element = (tag, text, className) => {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    };

    function period(kind) {
        const now = new Date();
        const year = now.getFullYear(), month = now.getMonth();
        const start = kind === "year" ? new Date(year, 0, 1) : kind === "month" ? new Date(year, month, 1) : now;
        const end = kind === "year" ? new Date(year, 11, 31) : kind === "month" ? new Date(year, month + 1, 0) : now;
        const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
        from.value = iso(start);
        to.value = iso(end);
    }

    function options(select, items, id, label, all, selected) {
        select.replaceChildren(new Option(all, ""));
        for (const [value, name] of journalOptions(items, id, label)) select.add(new Option(name, value));
        // Retain an explicit filter even when it has no facts in the new period.
        if (selected.value && ![...select.options].some(o => o.value === selected.value)) {
            select.add(new Option(selected.name, selected.value));
        }
        select.value = selected.value;
    }

    function arrangeFilters() {
        get("journalEntityFilters").append(...(view.value === "employee"
            ? [get("journalEmployeeLabel"), get("journalObjectLabel")]
            : [get("journalObjectLabel"), get("journalEmployeeLabel")]));
        get("journalIncludeLabel").hidden = !object.value.startsWith("object:");
    }

    function selectValue(select, value, name) {
        if (![...select.options].some(option => option.value === value)) select.add(new Option(name, value));
        select.value = value;
    }

    function history(kind, item) {
        const state = journalHistoryFilters({employee: employee.value, object: object.value,
            view: view.value, includeSubobjects: include.checked}, kind, item);
        if (kind === "employee") selectValue(employee, state.employee, item.full_name);
        else selectValue(object, state.object, journalItemLabel(item));
        view.value = state.view;
        arrangeFilters();
        load();
    }

    function historyLink(kind, item) {
        const button = element("button", kind === "employee" ? item.full_name : item.control_item_name, "journal-link");
        button.type = "button";
        button.addEventListener("click", () => history(kind, item));
        return button;
    }

    function render(result) {
        groups.replaceChildren();
        const facts = new Map(result.items.map(item => [item.id, item]));
        for (const group of result.groups) {
            const section = element("section", undefined, "journal-group");
            const title = element("h3");
            title.append(historyLink(result.view === "employee" ? "employee" : "object", group));
            section.append(title);
            if (group.control_item_type === "subobject") section.append(element("small", `Тип: Подобъект · Родительский объект: ${group.object_name}`));
            for (const pair of group.items) {
                const details = element("details", undefined, "journal-pair");
                details.open = Boolean(result.filters.employee_id || result.filters.object_id || result.filters.subobject_id || result.filters.subcontractor_id);
                const heading = element("summary", `${pair.full_name} — ${pair.control_item_name} · Дней контроля: ${pair.days_count}`);
                details.append(heading, element("p", `Период: ${displayDate(result.date_from)} — ${displayDate(result.date_to)}`),
                    element("p", `Даты контроля: ${pair.dates.map(displayDate).join(", ")}. Всего дней контроля: ${pair.days_count}`));
                if (pair.control_item_type === "subobject") details.append(element("small", `Тип: Подобъект · Родительский объект: ${pair.object_name}`));
                const wrapper = element("div", undefined, "table-wrapper");
                const table = element("table"), head = element("thead"), row = element("tr");
                for (const title of ["Дата", "Инженер", "Объект / Подобъект", "ПО", "Субподрядчик", "Категория"]) row.append(element("th", title));
                head.append(row);
                const body = element("tbody");
                for (const id of pair.fact_ids) {
                    const fact = facts.get(id);
                    const tr = element("tr");
                    const day = element("td", displayDate(fact.report_date));
                    const source = element("details");
                    source.append(element("summary", "Исходный файл"), element("small", fact.source_file));
                    day.append(source);
                    const engineer = element("td");
                    engineer.append(historyLink("employee", fact));
                    const position = element("td");
                    position.append(historyLink("object", fact));
                    if (fact.control_item_type === "subobject") position.append(element("small", `Подобъект · Родитель: ${fact.object_name}`, "journal-parent"));
                    tr.append(day, engineer, position, element("td", fact.po_name), element("td", fact.subcontractor_name || "—"), element("td", fact.category_name));
                    body.append(tr);
                }
                table.append(head, body);
                wrapper.append(table);
                details.append(wrapper);
                section.append(details);
            }
            groups.append(section);
        }
        const s = result.summary;
        const context = `${employee.selectedOptions[0]?.textContent || "Все инженеры"} · ${object.selectedOptions[0]?.textContent || "Все объекты / подобъекты"}`;
        summary.textContent = `Период: ${displayDate(result.date_from)} — ${displayDate(result.date_to)} · ${context}${object.value.startsWith("object:") && include.checked ? " (включая подобъекты)" : ""}. Основных объектов: ${s.objects_count} · Подобъектов: ${s.subobjects_count ?? 0} · Инженеров: ${s.employees_count} · Дней контроля: ${s.days_count} · Фактов: ${s.facts_count}`;
        if (employee.value) summary.textContent += ` · Даты контроля: ${result.dates.map(displayDate).join(", ") || "—"}`;
        message.textContent = result.items.length ? "Раскройте пару «Инженер — Объект / Подобъект», чтобы увидеть уникальные даты. Нажмите на ФИО или название в таблице для просмотра истории." : "За выбранный период с этими фильтрами записей нет.";
    }

    async function load() {
        const number = ++requestNumber;
        controller?.abort();
        controller = new AbortController();
        const signal = controller.signal;
        groups.replaceChildren();
        summary.textContent = "";
        message.textContent = "Загружаем журнал...";
        const selectedEmployee = {value: employee.value, name: employee.selectedOptions[0]?.textContent};
        const selectedSubcontractor = {value: subcontractor.value, name: subcontractor.selectedOptions[0]?.textContent};
        const selectedObject = {value: object.value, name: object.selectedOptions[0]?.textContent};
        try {
            const filtered = journalQuery(from.value, to.value, view.value, employee.value, object.value, include.checked, subcontractor.value);
            const request = async query => {
                const response = await fetch(`/api/daily-control-results?${query}`, {signal});
                const data = await response.json();
                if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось загрузить журнал");
                return data;
            };
            const result = await request(filtered);
            if (number !== requestNumber) return;
            options(employee, result.options.employees, "employee_id", "full_name", "Все инженеры", selectedEmployee);
            options(subcontractor, result.options.subcontractors || [], "id", "name", "Все субподрядчики", selectedSubcontractor);
            options(object, result.options.control_items.map(item => ({...item, label: journalItemLabel(item)})),
                "control_item_key", "label", "Все объекты / подобъекты", selectedObject);
            arrangeFilters();
            render(result);
        } catch (error) {
            if (number === requestNumber && error.name !== "AbortError") message.textContent = error.message;
        }
    }

    get("journalNavButton").addEventListener("click", event => {
        showMainSection(get("journalPage"), event.currentTarget);
        load();
    });
    get("journalFilters").addEventListener("submit", event => {event.preventDefault(); load();});
    view.addEventListener("change", () => {
        arrangeFilters();
        load();
    });
    // Invalidate results immediately when filters change; late responses cannot restore them.
    for (const input of [from, to, employee, object, include, subcontractor]) input.addEventListener("change", () => {
        ++requestNumber;
        controller?.abort();
        groups.replaceChildren();
        summary.textContent = "";
        arrangeFilters();
        message.textContent = "Нажмите «Показать», чтобы применить фильтры.";
    });
    const day = get("journalDay");
    day?.addEventListener("change", () => {
        if (!day.value || !day.validity.valid) return;
        from.value = day.value;
        to.value = day.value;
        load();
    });
    document.querySelectorAll("[data-journal-period]").forEach(button => button.addEventListener("click", () => {
        if (button.dataset.journalPeriod === "day") {
            day.hidden = false;
            day.value = from.value === to.value ? from.value : "";
            day.focus();
            try { day.showPicker?.(); } catch (_) { /* The date field remains available. */ }
            return;
        }
        if (day) day.hidden = true;
        period(button.dataset.journalPeriod);
        load();
    }));
    period("month");
    arrangeFilters();
}

if (typeof module !== "undefined") module.exports = {journalQuery, journalOptions, journalItemLabel, journalHistoryFilters, initJournal};
if (typeof document !== "undefined") initJournal();
