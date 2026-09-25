const folderPath = document.getElementById("folderPath");
const checkFolderButton = document.getElementById("checkFolderButton");
const folderInfo = document.getElementById("folderInfo");
const parseButton = document.getElementById("parseButton");
const modal = document.getElementById("modal");
const modalClose = document.getElementById("modalClose");
const detailsPanel = document.getElementById("detailsPanel");
const detailsOverlay = document.getElementById("detailsOverlay");
const detailsClose = document.getElementById("detailsClose");
const detailsCancel = document.getElementById("detailsCancel");
const newObjectSection = document.getElementById("newObjectSection");
const addObjectButton = document.getElementById("addObjectButton");
const resultTable = document.getElementById("resultTable");
const searchInput = document.getElementById('searchInput');
const statusFilter = document.getElementById('statusFilter');
const dateFilter=document.getElementById('dateFilter');
const clearResultsButton=document.getElementById('clearResultsButton');
const refreshButton=document.getElementById('refreshButton');
const downloadHtmlButton=document.getElementById('downloadHtmlButton');
window.processingReports = [];
let checkedPath = null;
let closeDetailsTimer;
let activeReportIndex = null;

folderPath.addEventListener("input", () => {
    checkedPath = null;
    parseButton.disabled = true;
    folderInfo.textContent = "Папка ещё не проверена";
    folderInfo.className = "folder-info";
});

checkFolderButton.addEventListener("click", async () => {
    checkFolderButton.disabled = true;
    folderPath.disabled = true;
    parseButton.disabled = true;
    try {
        const response = await fetch("/api/select-folder");
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось открыть выбор папки");
        if (result.status === "cancelled") return;
        if (!result.path) throw new Error("Не удалось получить путь к папке");
        folderPath.value = result.path;
        await checkFolder();
    } catch (error) {
        folderInfo.textContent = error.message || "Ошибка выбора папки";
        folderInfo.className = "folder-info error";
    } finally {
        checkFolderButton.disabled = false;
        folderPath.disabled = false;
        parseButton.disabled = checkedPath !== folderPath.value.trim();
    }
});

folderPath.addEventListener("change", checkFolder);

async function checkFolder() {
    const path = folderPath.value.trim();

    if (!path) {
        folderInfo.textContent = "Укажите путь к папке";
        folderInfo.className = "folder-info error";
        parseButton.disabled = true;
        return;
    }

    folderInfo.textContent = "Проверяем папку...";
    folderInfo.className = "folder-info";
    parseButton.disabled = true;
    checkedPath = null;
    checkFolderButton.disabled = true;

    try {
        const response = await fetch(
            "/api/check-folder?path=" + encodeURIComponent(path)
        );
        const result = await response.json();
        if (folderPath.value.trim() !== path) return;

        if (!response.ok) {
            folderInfo.textContent = result.message;
            folderInfo.className = "folder-info error";
            return;
        }

        folderInfo.textContent = `✓ Папка найдена. Word-отчётов: ${result.count}`;
        folderInfo.className = "folder-info success";
        parseButton.disabled = result.count === 0;
        checkedPath = result.count > 0 ? path : null;
    } catch (error) {
        folderInfo.textContent = "Ошибка соединения с сервером";
        folderInfo.className = "folder-info error";
    } finally {
        checkFolderButton.disabled = false;
    }
}

function updateStatistics(result) {
    const numbers = document.querySelectorAll(".stat-number");
    ["total", "ok", "warning", "error"].forEach((key, index) => {
        numbers[index].textContent = result[key];
    });
}

function buildStatus(report) {
    const badge = document.createElement("span");
    let status = "ok";
    let label = "✓ OK";
    if (report.status === "error") {
        status = "error";
        label = "Ошибка";
    } else if (report.employee_status === "similar") {
        status = "warning";
        label = "Согласовать сотрудника";
    } else if (report.employee_status === "new") {
        status = "warning";
        label = "Новый сотрудник";
    } else if (report.object_status === "similar") {
        status = "warning";
        label = "Согласовать объект";
    } else if (report.object_status === "new") {
        status = "warning";
        label = "Новый объект";
    } else if (report.status === "warning") {
        status = "warning";
        label = "Требует внимания";
    }
    badge.className = `status-badge ${status}`;
    badge.textContent = label;
    return badge;
}

function renderReports() {
    resultTable.replaceChildren();
    const query = searchInput.value.trim().toLocaleLowerCase("ru");
    window.processingReports.forEach((report, index) => {
        if (query && ![report.filename, report.full_name, report.object_name]
            .some(value => (value || "").toLocaleLowerCase("ru").includes(query))) return;
        if (dateFilter.value !== "all" && report.report_date !== dateFilter.value) return;
        if (statusFilter.value === "problem" && report.status === "ok") return;
        if (statusFilter.value === "new" && report.object_status !== "new" && report.employee_status !== "new") return;
        if (statusFilter.value === "ok" && report.status !== "ok") return;
        if (statusFilter.value === "error" && report.status !== "error") return;
        const row = document.createElement("tr");
        [index + 1, report.full_name, report.position, report.report_date,
            report.object_name, report.general_contractor, report.subcontractor]
            .forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = value || "—";
                row.append(cell);
            });
        row.firstElementChild.title = report.filename;
        const statusCell = document.createElement("td");
        statusCell.title = (report.problems || []).join("; ");
        statusCell.append(buildStatus(report));
        row.append(statusCell);
        const action = document.createElement("td");
        const button = document.getElementById("viewButtonTemplate")
            .content.firstElementChild.cloneNode(true);
        button.dataset.reportIndex = index;
        action.append(button);
        row.append(action);
        resultTable.append(row);
    });
    if (!resultTable.children.length) {
        const row = document.createElement("tr");
        row.className = "empty-row";
        const cell = document.createElement("td");
        cell.colSpan = 9;
        cell.textContent = "Нет отчётов для отображения";
        row.append(cell);
        resultTable.append(row);
    }
}

searchInput.addEventListener("input", renderReports);
statusFilter.addEventListener("change", renderReports);
dateFilter.addEventListener("change", renderReports);
refreshButton.addEventListener("click", renderReports);
clearResultsButton.addEventListener("click",()=>{window.processingReports=[];document.querySelectorAll(".stat-number").forEach(n=>n.textContent="—");renderReports();downloadHtmlButton.disabled=true;});
downloadHtmlButton.addEventListener("click",()=>window.open("/output/intermediate_report.html","_blank"));
document.getElementById("headerDate").textContent=new Intl.DateTimeFormat("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date());

parseButton.addEventListener("click", async () => {
    const path = folderPath.value.trim();
    if (parseButton.disabled || path !== checkedPath) return;
    const buttonContent = Array.from(parseButton.childNodes, node => node.cloneNode(true));
    parseButton.textContent = "Обработка...";
    parseButton.disabled = true;
    checkFolderButton.disabled = true;
    folderPath.disabled = true;
    closeDetails();
    window.processingReports = [];
    renderReports();
    document.querySelectorAll(".stat-number").forEach(node => { node.textContent = "—"; });
    folderInfo.className = "folder-info";
    folderInfo.textContent = "Обрабатываем отчёты...";
    try {
        const response = await fetch("/api/process-folder", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({path}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Ошибка обработки отчётов");
        window.processingReports = [
            ...result.reports,
            ...(result.processing_errors || []).map(error => ({
                filename: error.filename,
                status: "error",
                employee_status: "not_checked",
                object_status: "not_checked",
                problems: [error.error || "Не удалось обработать файл"],
            })),
        ];
        updateStatistics(result);
        dateFilter.innerHTML='<option value="all">Все даты</option>';
        [...new Set(window.processingReports.map(r=>r.report_date).filter(Boolean))].sort().reverse().forEach(d=>{const o=document.createElement("option");o.value=d;o.textContent=d;dateFilter.append(o)});
        downloadHtmlButton.disabled=false;
        document.getElementById("lastCheck").textContent="Последняя проверка: "+new Intl.DateTimeFormat("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date());
        renderReports();
        folderInfo.textContent = `Проверка завершена. Отчётов: ${result.total}`;
        folderInfo.className = "folder-info success";
    } catch (error) {
        folderInfo.textContent = error.message || "Ошибка соединения с сервером";
        folderInfo.className = "folder-info error";
    } finally {
        folderPath.disabled = false;
        parseButton.replaceChildren(...buttonContent);
        checkFolderButton.disabled = false;
        parseButton.disabled = checkedPath !== folderPath.value.trim();
    }
});

modalClose.addEventListener("click", () => {
    modal.hidden = true;
});

modal.addEventListener("click", event => {
    if (event.target === modal) modal.hidden = true;
});

function setDetailsValue(id, value) {
    document.getElementById(id).textContent = value || "—";
}

function buildCheckRow(label, status, parsedValue, candidates = []) {
    const row = document.createElement("div");
    row.style.padding = "12px 0";
    row.style.borderBottom = "1px solid rgba(148, 163, 184, .25)";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.justifyContent = "space-between";
    header.style.gap = "12px";
    header.style.alignItems = "center";

    const title = document.createElement("strong");
    title.textContent = label;
    header.append(title);

    const badge = document.createElement("span");
    const labels = {
        found: "НАЙДЕНО",
        similar: "ПОХОЖЕЕ",
        new: "НОВОЕ",
        not_checked: "НЕ УКАЗАНО",
    };
    badge.textContent = labels[status] || "НЕ ПРОВЕРЕНО";
    badge.className = `status-badge ${status === "found" ? "ok" : status === "not_checked" ? "" : status === "similar" || status === "new" ? "warning" : "error"}`;
    header.append(badge);
    row.append(header);

    const value = document.createElement("div");
    value.style.marginTop = "6px";
    value.textContent = parsedValue || "—";
    row.append(value);

    if (status === "found") {
        const note = document.createElement("small");
        note.textContent = "Совпадение найдено в базе данных.";
        row.append(note);
    } else if (status === "similar" && candidates.length) {
        const note = document.createElement("small");
        note.textContent = "Похожие записи в базе:";
        row.append(note);
        const list = document.createElement("ul");
        list.style.margin = "6px 0 0 18px";
        candidates.forEach(candidate => {
            const item = document.createElement("li");
            const entity = candidate.employee || candidate.object || candidate.po || candidate;
            const name = entity.full_name || entity.name || "—";
            const score = typeof candidate.similarity === "number" ? ` (${Math.round(candidate.similarity * 100)}%)` : "";
            item.textContent = name + score;
            list.append(item);
        });
        row.append(list);
    } else if (status === "similar") {
        const note = document.createElement("small");
        note.textContent = "Найдено похожее значение. Требуется согласование.";
        row.append(note);
    } else if (status === "new") {
        const note = document.createElement("small");
        note.textContent = "Такой записи в базе данных нет.";
        row.append(note);
    } else if (status === "not_checked") {
        const note = document.createElement("small");
        note.textContent = "Значение в отчёте не указано — проверка не требуется.";
        row.append(note);
    }

    return row;
}

function openDetails(report) {
    clearTimeout(closeDetailsTimer);
    setDetailsValue("detailsFile", report.filename);
    setDetailsValue("detailsEmployee", report.full_name);
    setDetailsValue("detailsPosition", report.position);
    setDetailsValue("detailsDate", report.report_date);
    setDetailsValue("detailsObject", report.object_name);
    setDetailsValue("detailsGeneralContractor", report.general_contractor);
    setDetailsValue("detailsSubcontractor", report.subcontractor);

    document.getElementById("detailsTitle").textContent = "Результат проверки";

    const databaseStatus = document.getElementById("databaseStatus");
    databaseStatus.className = "database-status";
    databaseStatus.replaceChildren();

    databaseStatus.append(
        buildCheckRow("Сотрудник", report.employee_status, report.full_name, report.employee_candidates || []),
        buildCheckRow("Объект", report.object_status, report.object_name, report.object_candidates || []),
        buildCheckRow("Генподрядчик", report.general_contractor_status, report.general_contractor, report.general_contractor_candidates || []),
        buildCheckRow("Субподрядчик", report.subcontractor_status || (report.subcontractor ? "not_checked" : "not_checked"), report.subcontractor, report.subcontractor_candidates || [])
    );

    // На этом этапе окно только показывает результаты сравнения.
    // Согласование и добавление новых записей подключим отдельным шагом.
    newObjectSection.hidden = true;
    addObjectButton.hidden = true;

    const objectComment = document.getElementById("objectComment");
    if (objectComment) objectComment.value = "";

    detailsOverlay.hidden = false;
    requestAnimationFrame(() => detailsPanel.classList.add("open"));
}

function closeDetails() {
    detailsPanel.classList.remove("open");
    clearTimeout(closeDetailsTimer);
    closeDetailsTimer = setTimeout(() => { detailsOverlay.hidden = true; }, 250);
}

document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeDetails();
});

detailsClose.addEventListener("click", closeDetails);
detailsCancel.addEventListener("click", closeDetails);
detailsOverlay.addEventListener("click", closeDetails);

resultTable.addEventListener("click", event => {
    const button = event.target.closest(".view-button");
    if (!button) return;

    const index = Number(button.dataset.reportIndex);
    const report = window.processingReports[index];
    if (!report) return;

    activeReportIndex = index;
    openDetails(report);
});



// ===== Add parsed object to database =====
function removeNewObjectProblems(report) {
    if (!Array.isArray(report.problems)) return;
    report.problems = report.problems.filter(problem => {
        const text = String(problem || "").toLocaleLowerCase("ru");
        return !text.includes("новый объект") &&
               !text.includes("объект отсутствует") &&
               !text.includes("не найден в базе");
    });
}

addObjectButton?.addEventListener("click", async () => {
    if (activeReportIndex === null) return;
    const report = window.processingReports[activeReportIndex];
    if (!report) return;

    const name = document.getElementById("newObjectName").value.trim();
    if (!name) {
        alert("Введите наименование объекта");
        return;
    }

    const oldText = addObjectButton.textContent;
    addObjectButton.disabled = true;
    addObjectButton.textContent = "Добавление...";

    try {
        const response = await fetch("/api/objects", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось добавить объект");

        report.object_name = result.object?.name || name;
        report.object_id = result.object?.id ?? result.id ?? report.object_id;
        report.object_status = "found";
        removeNewObjectProblems(report);

        const hasEmployeeProblem =
            report.employee_status === "new" ||
            report.employee_status === "similar";

        if (!hasEmployeeProblem && (!report.problems || report.problems.length === 0)) {
            report.status = "ok";
        }

        updateStatistics({
            total: window.processingReports.length,
            ok: window.processingReports.filter(item => item.status === "ok").length,
            warning: window.processingReports.filter(item => item.status === "warning").length,
            error: window.processingReports.filter(item => item.status === "error").length,
        });
        renderReports();

        document.getElementById("detailsTitle").textContent = "Объект добавлен";
        const databaseStatus = document.getElementById("databaseStatus");
        databaseStatus.textContent = "✓ Объект успешно добавлен в базу данных.";
        databaseStatus.className = "database-status ok";
        newObjectSection.hidden = true;
        addObjectButton.hidden = true;

        if (typeof loadObjects === "function") loadObjects().catch(() => {});
    } catch (error) {
        const databaseStatus = document.getElementById("databaseStatus");
        databaseStatus.textContent = error.message || "Ошибка добавления объекта";
        databaseStatus.className = "database-status error";
    } finally {
        addObjectButton.disabled = false;
        addObjectButton.textContent = oldText;
    }
});

// ===== Construction objects / categories =====
const objectsNavButton = document.getElementById("objectsNavButton");
const processingPage = document.getElementById("processingPage");
const objectsPage = document.getElementById("objectsPage");
const backToProcessingButton = document.getElementById("backToProcessingButton");
const categoryList = document.getElementById("categoryList");
const categoryModal = document.getElementById("categoryModal");
const categoryModalTitle = document.getElementById("categoryModalTitle");
const categoryModalClose = document.getElementById("categoryModalClose");
const categoryModalCancel = document.getElementById("categoryModalCancel");
const categoryModalSave = document.getElementById("categoryModalSave");
const categoryNameInput = document.getElementById("categoryNameInput");
const categoryNumberPreview = document.getElementById("categoryNumberPreview");
const categoryModalError = document.getElementById("categoryModalError");
let categoryTree = [];
let categoryEditId = null;
let categoryParentId = null;

function setActiveNav(button) {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
    if (button) button.classList.add("active");
}

async function loadCategories() {
    const response = await fetch("/api/object-categories");
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Не удалось загрузить категории");
    categoryTree = result.items || [];
    renderCategoryList();
}

// ===== Construction objects / objects directory =====
const objectsTab = document.getElementById("objectsTab");
const objectsPanel = document.getElementById("objectsPanel");
const objectList = document.getElementById("objectList");
const addDirectoryObjectButton = document.getElementById("addDirectoryObjectButton");
const objectSearchInput = document.getElementById("objectSearchInput");
const objectCount = document.getElementById("objectCount");
const objectDirectoryModal = document.getElementById("objectDirectoryModal");
const objectDirectoryModalTitle = document.getElementById("objectDirectoryModalTitle");
const objectDirectoryModalClose = document.getElementById("objectDirectoryModalClose");
const objectDirectoryModalCancel = document.getElementById("objectDirectoryModalCancel");
const objectDirectoryModalSave = document.getElementById("objectDirectoryModalSave");
const objectDirectoryNameInput = document.getElementById("objectDirectoryNameInput");
const objectDirectoryModalError = document.getElementById("objectDirectoryModalError");
let objectItems = [];
let objectEditId = null;

async function loadObjects() {
    const response = await fetch("/api/objects");
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Не удалось загрузить объекты");
    objectItems = result.items || result.objects || [];
    renderObjectList();
}

function renderObjectList() {
    if (!objectList) return;
    objectList.replaceChildren();
    const query = (objectSearchInput?.value || "").trim().toLocaleLowerCase("ru");
    const items = objectItems.filter(item =>
        !query || (item.name || "").toLocaleLowerCase("ru").includes(query)
    );
    if (objectCount) objectCount.textContent = `Показано: ${items.length} из ${objectItems.length}`;

    if (!items.length) {
        objectList.innerHTML = `<div class="category-empty">${objectItems.length ? "Объекты не найдены" : "Объекты пока не добавлены"}</div>`;
        return;
    }

    items.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "category-row";
        row.innerHTML = `
            <div class="category-number"></div>
            <div class="category-name"><strong></strong></div>
            <div class="category-actions">
                <button type="button" class="category-icon-button edit-object-directory" title="Редактировать">✎</button>
                <button type="button" class="category-icon-button danger delete-object-directory" title="Удалить">🗑</button>
            </div>`;
        row.querySelector(".category-number").textContent = index + 1;
        row.querySelector("strong").textContent = item.name || "—";
        row.querySelector(".edit-object-directory").dataset.id = item.id;
        row.querySelector(".delete-object-directory").dataset.id = item.id;
        objectList.append(row);
    });
}

function openObjectDirectoryModal(item = null) {
    objectEditId = item?.id || null;
    objectDirectoryModalTitle.textContent = item ? "Редактирование объекта" : "Добавить объект";
    objectDirectoryModalSave.textContent = item ? "Сохранить" : "Добавить";
    objectDirectoryNameInput.value = item?.name || "";
    objectDirectoryModalError.hidden = true;
    objectDirectoryModalError.textContent = "";
    objectDirectoryModal.hidden = false;
    setTimeout(() => objectDirectoryNameInput.focus(), 0);
}

function closeObjectDirectoryModal() {
    objectDirectoryModal.hidden = true;
    objectEditId = null;
}

objectSearchInput?.addEventListener("input", renderObjectList);
addDirectoryObjectButton?.addEventListener("click", () => openObjectDirectoryModal());
objectDirectoryModalClose?.addEventListener("click", closeObjectDirectoryModal);
objectDirectoryModalCancel?.addEventListener("click", closeObjectDirectoryModal);
objectDirectoryModal?.addEventListener("click", event => {
    if (event.target === objectDirectoryModal) closeObjectDirectoryModal();
});

objectList?.addEventListener("click", async event => {
    const editButton = event.target.closest(".edit-object-directory");
    if (editButton) {
        const item = objectItems.find(value => String(value.id) === editButton.dataset.id);
        if (item) openObjectDirectoryModal(item);
        return;
    }

    const deleteButton = event.target.closest(".delete-object-directory");
    if (!deleteButton) return;
    const item = objectItems.find(value => String(value.id) === deleteButton.dataset.id);
    if (!item) return;

    if (!confirm(`Удалить объект «${item.name}»?`)) return;

    try {
        const response = await fetch(`/api/objects/${item.id}`, {method: "DELETE"});
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось удалить объект");
        await loadObjects();
        if (typeof employeeItems !== "undefined" && employeeItems.length) await loadEmployees();
    } catch (error) {
        alert(error.message);
    }
});

objectDirectoryModalSave?.addEventListener("click", async () => {
    const name = objectDirectoryNameInput.value.trim();
    if (!name) {
        objectDirectoryModalError.textContent = "Введите наименование объекта";
        objectDirectoryModalError.hidden = false;
        return;
    }

    objectDirectoryModalSave.disabled = true;
    objectDirectoryModalError.hidden = true;
    try {
        const response = await fetch(
            objectEditId ? `/api/objects/${objectEditId}` : "/api/objects",
            {
                method: objectEditId ? "PATCH" : "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({name}),
            }
        );
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось сохранить объект");
        closeObjectDirectoryModal();
        await loadObjects();
    } catch (error) {
        objectDirectoryModalError.textContent = error.message;
        objectDirectoryModalError.hidden = false;
    } finally {
        objectDirectoryModalSave.disabled = false;
    }
});

function categoryNumber(parent, child = null) {
    return child ? `${parent.sort_order}.${child.sort_order}` : String(parent.sort_order);
}

function renderCategoryList() {
    if (!categoryList) return;
    categoryList.replaceChildren();
    if (!categoryTree.length) {
        const empty = document.createElement("div");
        empty.className = "category-empty";
        empty.textContent = "Категории не найдены";
        categoryList.append(empty);
        return;
    }
    categoryTree.forEach(parent => {
        const row = document.createElement("div");
        row.className = "category-row";
        row.innerHTML = `<div class="category-number"></div><div class="category-name"><strong></strong><small></small></div><div class="category-actions"><span class="system-category-lock">🔒 системная</span></div>`;
        row.querySelector(".category-number").textContent = categoryNumber(parent);
        row.querySelector("strong").textContent = parent.name;
        row.querySelector("small").textContent = parent.children?.length ? `${parent.children.length} подкатегории` : "Основная категория";
        categoryList.append(row);

        (parent.children || []).forEach(child => {
            const childRow = document.createElement("div");
            childRow.className = "category-row child";
            childRow.innerHTML = `<div class="category-number"></div><div class="category-name"><strong></strong></div><div class="category-actions"><button type="button" class="category-icon-button edit-category" title="Переименовать">✎</button><button type="button" class="category-icon-button danger delete-category" title="Удалить">🗑</button></div>`;
            childRow.querySelector(".category-number").textContent = categoryNumber(parent, child);
            childRow.querySelector("strong").textContent = child.name;
            childRow.querySelector(".edit-category").dataset.id = child.id;
            childRow.querySelector(".delete-category").dataset.id = child.id;
            categoryList.append(childRow);
        });

        if (parent.name === "Прочее") {
            const add = document.createElement("div");
            add.className = "category-add";
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "+ Добавить подкатегорию";
            button.dataset.parentId = parent.id;
            button.dataset.nextOrder = (parent.children?.length || 0) + 1;
            add.append(button);
            categoryList.append(add);
        }
    });
}


objectsNavButton?.addEventListener("click", async () => {
    closeDetails();
    processingPage.hidden = true;
    objectsPage.hidden = false;
    setActiveNav(objectsNavButton);
    activateObjectTab(objectsTab);
    try { await loadObjects(); }
    catch (error) { objectList.innerHTML = `<div class="category-empty">${error.message}</div>`; }
});

backToProcessingButton?.addEventListener("click", () => {
    objectsPage.hidden = true;
    processingPage.hidden = false;
    setActiveNav(document.querySelector(".nav-item:first-child"));
});

function openCategoryModal({parentId, nextOrder, item = null}) {
    categoryParentId = parentId || item?.parent_id;
    categoryEditId = item?.id || null;
    categoryModalTitle.textContent = item ? "Переименовать подкатегорию" : "Добавить подкатегорию";
    categoryModalSave.textContent = item ? "Сохранить" : "Добавить";
    categoryNameInput.value = item?.name || "";
    categoryNumberPreview.textContent = item ? "Номер подкатегории не изменится." : `Номер будет присвоен автоматически: 6.${nextOrder}`;
    categoryModalError.hidden = true;
    categoryModalError.textContent = "";
    categoryModal.hidden = false;
    setTimeout(() => categoryNameInput.focus(), 0);
}

function closeCategoryModal() { categoryModal.hidden = true; }
categoryModalClose?.addEventListener("click", closeCategoryModal);
categoryModalCancel?.addEventListener("click", closeCategoryModal);
categoryModal?.addEventListener("click", e => { if (e.target === categoryModal) closeCategoryModal(); });

categoryList?.addEventListener("click", async event => {
    const addButton = event.target.closest(".category-add button");
    if (addButton) {
        openCategoryModal({parentId: Number(addButton.dataset.parentId), nextOrder: Number(addButton.dataset.nextOrder)});
        return;
    }
    const editButton = event.target.closest(".edit-category");
    if (editButton) {
        const id = Number(editButton.dataset.id);
        const parent = categoryTree.find(p => (p.children || []).some(c => c.id === id));
        const item = parent?.children.find(c => c.id === id);
        if (item) openCategoryModal({item});
        return;
    }
    const deleteButton = event.target.closest(".delete-category");
    if (deleteButton) {
        const id = Number(deleteButton.dataset.id);
        const parent = categoryTree.find(p => (p.children || []).some(c => c.id === id));
        const item = parent?.children.find(c => c.id === id);
        if (!item || !confirm(`Удалить подкатегорию «${item.name}»?`)) return;
        try {
            const response = await fetch(`/api/object-categories/${id}`, {method: "DELETE"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || "Не удалось удалить подкатегорию");
            await loadCategories();
        } catch (error) { alert(error.message); }
    }
});

categoryModalSave?.addEventListener("click", async () => {
    const name = categoryNameInput.value.trim();
    if (!name) {
        categoryModalError.textContent = "Введите название подкатегории";
        categoryModalError.hidden = false;
        return;
    }
    categoryModalSave.disabled = true;
    categoryModalError.hidden = true;
    try {
        const url = categoryEditId ? `/api/object-categories/${categoryEditId}` : `/api/object-categories/${categoryParentId}/children`;
        const response = await fetch(url, {
            method: categoryEditId ? "PATCH" : "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось сохранить подкатегорию");
        closeCategoryModal();
        await loadCategories();
    } catch (error) {
        categoryModalError.textContent = error.message;
        categoryModalError.hidden = false;
    } finally { categoryModalSave.disabled = false; }
});

// Загружаем справочник категорий для вкладки и назначений.
loadCategories().catch(() => {});


// ===== Construction objects / PO directory =====
const categoriesTab = document.getElementById("categoriesTab");
const poTab = document.getElementById("poTab");
const categoriesPanel = document.getElementById("categoriesPanel");
const poPanel = document.getElementById("poPanel");
const poList = document.getElementById("poList");
const addPoButton = document.getElementById("addPoButton");
const poModal = document.getElementById("poModal");
const poModalTitle = document.getElementById("poModalTitle");
const poModalClose = document.getElementById("poModalClose");
const poModalCancel = document.getElementById("poModalCancel");
const poModalSave = document.getElementById("poModalSave");
const poNameInput = document.getElementById("poNameInput");
const poModalError = document.getElementById("poModalError");
let poItems = [];
let poEditId = null;

function activateObjectTab(tab) {
    [objectsTab, categoriesTab, poTab].forEach(button => button?.classList.remove("active"));
    tab?.classList.add("active");
    if (objectsPanel) objectsPanel.hidden = tab !== objectsTab;
    categoriesPanel.hidden = tab !== categoriesTab;
    poPanel.hidden = tab !== poTab;
}

async function loadPoTypes() {
    const response = await fetch("/api/po-types");
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Не удалось загрузить ПО");
    poItems = result.items || [];
    renderPoList();
}

function renderPoList() {
    if (!poList) return;
    poList.replaceChildren();

    if (!poItems.length) {
        const empty = document.createElement("div");
        empty.className = "category-empty";
        empty.textContent = "ПО пока не добавлены";
        poList.append(empty);
        return;
    }

    poItems.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "category-row po-row";
        row.innerHTML = `
            <div class="category-number"></div>
            <div class="category-name"><strong></strong></div>
            <div class="category-actions">
                <button type="button" class="category-icon-button edit-po" title="Переименовать">✎</button>
                <button type="button" class="category-icon-button danger delete-po" title="Удалить">🗑</button>
            </div>`;
        row.querySelector(".category-number").textContent = index + 1;
        row.querySelector("strong").textContent = item.name;
        row.querySelector(".edit-po").dataset.id = item.id;
        row.querySelector(".delete-po").dataset.id = item.id;
        poList.append(row);
    });
}


function openPoModal(item = null) {
    poEditId = item?.id || null;
    poModalTitle.textContent = item ? "Переименовать ПО" : "Добавить ПО";
    poModalSave.textContent = item ? "Сохранить" : "Добавить";
    poNameInput.value = item?.name || "";
    poModalError.hidden = true;
    poModalError.textContent = "";
    poModal.hidden = false;
    setTimeout(() => poNameInput.focus(), 0);
}

function closePoModal() {
    poModal.hidden = true;
}

objectsTab?.addEventListener("click", async () => {
    activateObjectTab(objectsTab);
    try { await loadObjects(); }
    catch (error) { objectList.innerHTML = `<div class="category-empty">${error.message}</div>`; }
});

categoriesTab?.addEventListener("click", async () => {
    activateObjectTab(categoriesTab);
    try { await loadCategories(); }
    catch (error) { categoryList.innerHTML = `<div class="category-empty">${error.message}</div>`; }
});

poTab?.addEventListener("click", async () => {
    activateObjectTab(poTab);
    try { await loadPoTypes(); }
    catch (error) { poList.innerHTML = `<div class="category-empty">${error.message}</div>`; }
});

addPoButton?.addEventListener("click", () => openPoModal());
poModalClose?.addEventListener("click", closePoModal);
poModalCancel?.addEventListener("click", closePoModal);
poModal?.addEventListener("click", event => {
    if (event.target === poModal) closePoModal();
});

poList?.addEventListener("click", async event => {
    const editButton = event.target.closest(".edit-po");
    if (editButton) {
        const item = poItems.find(value => String(value.id) === editButton.dataset.id);
        if (item) openPoModal(item);
        return;
    }

    const deleteButton = event.target.closest(".delete-po");
    if (!deleteButton) return;

    const item = poItems.find(value => String(value.id) === deleteButton.dataset.id);
    if (!item || !confirm(`Удалить ПО «${item.name}»?`)) return;

    try {
        const response = await fetch(`/api/po-types/${item.id}`, {method: "DELETE"});
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось удалить ПО");
        await loadPoTypes();
    } catch (error) {
        alert(error.message);
    }
});

poModalSave?.addEventListener("click", async () => {
    const name = poNameInput.value.trim();
    if (!name) {
        poModalError.textContent = "Введите наименование ПО";
        poModalError.hidden = false;
        return;
    }

    poModalSave.disabled = true;
    poModalError.hidden = true;

    try {
        const url = poEditId ? `/api/po-types/${poEditId}` : "/api/po-types";
        const response = await fetch(url, {
            method: poEditId ? "PATCH" : "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Не удалось сохранить ПО");
        closePoModal();
        await loadPoTypes();
    } catch (error) {
        poModalError.textContent = error.message;
        poModalError.hidden = false;
    } finally {
        poModalSave.disabled = false;
    }
});

// Загружаем справочник ПО для вкладки и назначений.
loadPoTypes().catch(() => {});

// ===== Employees / positions =====
const employeesNavButton=document.getElementById("employeesNavButton"),employeesPage=document.getElementById("employeesPage"),backFromEmployeesButton=document.getElementById("backFromEmployeesButton"),employeesTab=document.getElementById("employeesTab"),positionsTab=document.getElementById("positionsTab"),employeesPanel=document.getElementById("employeesPanel"),positionsPanel=document.getElementById("positionsPanel"),positionList=document.getElementById("positionList"),addPositionButton=document.getElementById("addPositionButton"),positionModal=document.getElementById("positionModal"),positionModalTitle=document.getElementById("positionModalTitle"),positionModalClose=document.getElementById("positionModalClose"),positionModalCancel=document.getElementById("positionModalCancel"),positionModalSave=document.getElementById("positionModalSave"),positionNameInput=document.getElementById("positionNameInput"),positionDescriptionInput=document.getElementById("positionDescriptionInput"),positionModalError=document.getElementById("positionModalError");
let positionItems=[],positionEditId=null;
function showMainSection(section,nav){processingPage.hidden=section!==processingPage;objectsPage.hidden=section!==objectsPage;employeesPage.hidden=section!==employeesPage;setActiveNav(nav)}
function activateEmployeeTab(tab){[employeesTab,positionsTab].forEach(b=>b?.classList.remove("active"));tab?.classList.add("active");employeesPanel.hidden=tab!==employeesTab;positionsPanel.hidden=tab!==positionsTab}
async function loadPositions(){const r=await fetch("/api/positions"),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось загрузить должности");positionItems=x.items||[];renderPositionList()}
function renderPositionList(){positionList.replaceChildren();if(!positionItems.length){positionList.innerHTML='<div class="category-empty">Должности не найдены</div>';return}const header=document.createElement("div");header.className="position-table-header";header.innerHTML="<strong>Должность</strong><strong>Описание действий</strong><strong>Действия</strong>";positionList.append(header);positionItems.forEach(item=>{const row=document.createElement("div");row.className="position-table-row";row.innerHTML='<div class="position-title"></div><div class="position-description"></div><div class="category-actions"><button type="button" class="category-icon-button edit-position" title="Редактировать">✎</button><button type="button" class="category-icon-button danger delete-position" title="Удалить">🗑</button></div>';row.querySelector(".position-title").textContent=item.name;const d=row.querySelector(".position-description");d.textContent=item.action_description||"Описание действий не заполнено";if(!item.action_description)d.classList.add("empty-description");row.querySelector(".edit-position").dataset.id=item.id;row.querySelector(".delete-position").dataset.id=item.id;positionList.append(row)})}
function openPositionModal(item=null){positionEditId=item?.id||null;positionModalTitle.textContent=item?"Редактировать должность":"Добавить должность";positionModalSave.textContent=item?"Сохранить":"Добавить";positionNameInput.value=item?.name||"";positionDescriptionInput.value=item?.action_description||"";positionModalError.hidden=true;positionModal.hidden=false;setTimeout(()=>positionNameInput.focus(),0)}
function closePositionModal(){positionModal.hidden=true}
employeesNavButton?.addEventListener("click",()=>{closeDetails();showMainSection(employeesPage,employeesNavButton);activateEmployeeTab(employeesTab)});
backFromEmployeesButton?.addEventListener("click",()=>showMainSection(processingPage,document.querySelector(".nav-item:first-child")));
employeesTab?.addEventListener("click",()=>activateEmployeeTab(employeesTab));
positionsTab?.addEventListener("click",async()=>{activateEmployeeTab(positionsTab);try{await loadPositions()}catch(e){positionList.innerHTML=`<div class="category-empty">${e.message}</div>`}});
addPositionButton?.addEventListener("click",()=>openPositionModal());
positionModalClose?.addEventListener("click",closePositionModal);positionModalCancel?.addEventListener("click",closePositionModal);positionModal?.addEventListener("click",e=>{if(e.target===positionModal)closePositionModal()});
positionList?.addEventListener("click",async e=>{const eb=e.target.closest(".edit-position");if(eb){const item=positionItems.find(x=>String(x.id)===eb.dataset.id);if(item)openPositionModal(item);return}const db=e.target.closest(".delete-position");if(!db)return;const item=positionItems.find(x=>String(x.id)===db.dataset.id);if(!item||!confirm(`Удалить должность «${item.name}»?`))return;try{const r=await fetch(`/api/positions/${item.id}`,{method:"DELETE"}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить должность");await loadPositions()}catch(err){alert(err.message)}});
positionModalSave?.addEventListener("click",async()=>{const name=positionNameInput.value.trim();if(!name){positionModalError.textContent="Введите название должности";positionModalError.hidden=false;return}positionModalSave.disabled=true;positionModalError.hidden=true;try{const url=positionEditId?`/api/positions/${positionEditId}`:"/api/positions",r=await fetch(url,{method:positionEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,action_description:positionDescriptionInput.value.trim()||null})}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить должность");closePositionModal();await loadPositions()}catch(err){positionModalError.textContent=err.message;positionModalError.hidden=false}finally{positionModalSave.disabled=false}});


// ===== Employees CRUD =====
const employeeList=document.getElementById("employeeList");
const addEmployeeButton=document.getElementById("addEmployeeButton");
const employeeSearchInput=document.getElementById("employeeSearchInput");
const employeeCount=document.getElementById("employeeCount");
const employeeModal=document.getElementById("employeeModal");
const employeeModalTitle=document.getElementById("employeeModalTitle");
const employeeModalClose=document.getElementById("employeeModalClose");
const employeeModalCancel=document.getElementById("employeeModalCancel");
const employeeModalSave=document.getElementById("employeeModalSave");
const employeeNameInput=document.getElementById("employeeNameInput");
const employeePositionSelect=document.getElementById("employeePositionSelect");
const employeeActionDescription=document.getElementById("employeeActionDescription");
const employeePhoneInput=document.getElementById("employeePhoneInput");
const employeeCrewSelect=document.getElementById("employeeCrewSelect");
const employeeCrewPreview=document.getElementById("employeeCrewPreview");
const employeeModalError=document.getElementById("employeeModalError");
const employeeAssignmentsSection=document.getElementById("employeeAssignmentsSection");
const employeeObjectsCount=document.getElementById("employeeObjectsCount");
const employeeAssignmentsList=document.getElementById("employeeAssignmentsList");
const addAssignmentButton=document.getElementById("addAssignmentButton");
const assignmentEditor=document.getElementById("assignmentEditor");
const assignmentObjectSelect=document.getElementById("assignmentObjectSelect");
const assignmentPoSelect=document.getElementById("assignmentPoSelect");
const assignmentCategorySelect=document.getElementById("assignmentCategorySelect");
const assignmentCancelButton=document.getElementById("assignmentCancelButton");
const assignmentSaveButton=document.getElementById("assignmentSaveButton");
const assignmentError=document.getElementById("assignmentError");
let employeeAssignments=[];let assignmentEditId=null;

let employeeItems=[];
let crewItems=[];
let employeeEditId=null;

async function loadEmployees(){
    const response=await fetch("/api/employees");
    const result=await response.json();
    if(!response.ok) throw new Error(result.message||"Не удалось загрузить сотрудников");
    employeeItems=result.items||[];
    renderEmployees();
}
async function loadCrews(){
    const response=await fetch("/api/crews");
    const result=await response.json();
    if(!response.ok) throw new Error(result.message||"Не удалось загрузить экипажи");
    crewItems=result.items||[];
}
function renderEmployees(){
    if(!employeeList)return;
    employeeList.replaceChildren();
    const q=(employeeSearchInput?.value||"").trim().toLocaleLowerCase("ru");
    const items=employeeItems.filter(item=>!q||[item.full_name,item.position_name,item.phone,item.crew_name].some(v=>(v||"").toLocaleLowerCase("ru").includes(q)));
    if(employeeCount)employeeCount.textContent=`Показано: ${items.length} из ${employeeItems.length}`;
    if(!items.length){employeeList.innerHTML='<div class="category-empty">Сотрудники не найдены</div>';return}
    const header=document.createElement("div");
    header.className="employee-table-header";
    header.innerHTML="<strong>ФИО</strong><strong>Должность</strong><strong>Телефон</strong><strong>Экипаж</strong><strong>Объектов</strong><strong>Действия</strong>";
    employeeList.append(header);
    items.forEach(item=>{
        const row=document.createElement("div");
        row.className="employee-table-row";
        row.innerHTML='<div class="employee-name"></div><div class="employee-position"></div><div class="employee-phone"></div><div class="employee-crew"></div><div class="employee-objects-count"></div><div class="category-actions"><button type="button" class="category-icon-button edit-employee" title="Редактировать">✎</button><button type="button" class="category-icon-button danger delete-employee" title="Удалить">🗑</button></div>';
        row.querySelector(".employee-name").textContent=item.full_name||"—";
        const p=row.querySelector(".employee-position"); p.textContent=item.position_name||"—"; if(item.action_description)p.title=item.action_description;
        row.querySelector(".employee-phone").textContent=item.phone||"—";
        const crew=crewItems.find(x=>x.id===item.crew_id); row.querySelector(".employee-crew").textContent=crew?.driver_full_name||item.crew_name||"—";
        row.querySelector(".employee-objects-count").textContent=Number(item.objects_count)||0;
        row.querySelector(".edit-employee").dataset.id=item.id;
        row.querySelector(".delete-employee").dataset.id=item.id;
        employeeList.append(row);
    });
}
function fillEmployeeSelects(){
    employeePositionSelect.innerHTML='<option value="">Не выбрана</option>';
    (typeof positionItems!=="undefined"?positionItems:[]).forEach(item=>{
        const o=document.createElement("option");o.value=item.id;o.textContent=item.name;employeePositionSelect.append(o);
    });
    employeeCrewSelect.innerHTML='<option value="">Не назначен</option>';
    crewItems.forEach(item=>{const o=document.createElement("option");o.value=item.id;o.textContent=item.driver_full_name||"Водитель не указан";employeeCrewSelect.append(o)});
}
function updateEmployeeDescription(){
    const item=(typeof positionItems!=="undefined"?positionItems:[]).find(x=>String(x.id)===employeePositionSelect.value);
    employeeActionDescription.value=item?.action_description||"";
}
function updateEmployeeCrewPreview(){
    const item=crewItems.find(x=>String(x.id)===employeeCrewSelect.value);
    if(!item){employeeCrewPreview.hidden=true;employeeCrewPreview.textContent="";return}
    const vehicle=[item.vehicle_make,item.vehicle_plate].filter(Boolean).join(" · ");
    employeeCrewPreview.textContent=[item.driver_full_name,item.driver_phone,vehicle].filter(Boolean).join(" | ");
    employeeCrewPreview.hidden=false;
}
async function loadEmployeeAssignments(employeeId){const r=await fetch(`/api/employees/${employeeId}/assignments`),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось загрузить назначения");employeeAssignments=x.items||[];employeeObjectsCount.textContent=`Объектов: ${x.objects_count||0}`;renderEmployeeAssignments()}
function renderEmployeeAssignments(){employeeAssignmentsList.replaceChildren();if(!employeeAssignments.length){employeeAssignmentsList.innerHTML='<div class="assignment-empty">Назначений пока нет</div>';return}employeeAssignments.forEach(item=>{const row=document.createElement("div");row.className="assignment-row";row.innerHTML='<div class="assignment-main"><strong class="assignment-object"></strong><span class="assignment-po"></span><span class="assignment-category"></span></div><div class="category-actions"><button type="button" class="category-icon-button edit-assignment">✎</button><button type="button" class="category-icon-button danger delete-assignment">🗑</button></div>';row.querySelector(".assignment-object").textContent=item.object_name||"—";row.querySelector(".assignment-po").textContent=`ПО: ${item.po_name||"—"}`;row.querySelector(".assignment-category").textContent=`Категория: ${item.category_name||"—"}`;row.querySelector(".edit-assignment").dataset.id=item.id;row.querySelector(".delete-assignment").dataset.id=item.id;employeeAssignmentsList.append(row)})}
async function loadAssignmentDictionaries(){const [a,b,c]=await Promise.all([fetch("/api/objects"),fetch("/api/po-types"),fetch("/api/object-categories")]);const [ax,bx,cx]=await Promise.all([a.json(),b.json(),c.json()]);if(!a.ok)throw new Error(ax.message||"Не удалось загрузить объекты");if(!b.ok)throw new Error(bx.message||"Не удалось загрузить ПО");if(!c.ok)throw new Error(cx.message||"Не удалось загрузить категории");assignmentObjectSelect.innerHTML='<option value="">Выберите объект</option>';(ax.items||ax.objects||[]).forEach(x=>assignmentObjectSelect.add(new Option(x.name,x.id)));assignmentPoSelect.innerHTML='<option value="">Выберите ПО</option>';(bx.items||[]).forEach(x=>assignmentPoSelect.add(new Option(x.name,x.id)));assignmentCategorySelect.innerHTML='<option value="">Выберите категорию</option>';(cx.items||[]).forEach(x=>assignmentCategorySelect.add(new Option(x.name,x.id)))}
async function openAssignmentEditor(item=null){try{await loadAssignmentDictionaries();assignmentEditId=item?.id||null;assignmentObjectSelect.value=item?String(item.object_id):"";assignmentPoSelect.value=item?String(item.po_id):"";assignmentCategorySelect.value=item?String(item.category_id):"";assignmentSaveButton.textContent=item?"Сохранить":"Добавить";assignmentError.hidden=true;assignmentEditor.hidden=false}catch(e){alert(e.message)}}
function closeAssignmentEditor(){assignmentEditor.hidden=true;assignmentEditId=null}

async function openEmployeeModal(item=null){
    employeeEditId=item?.id||null;
    employeeModalTitle.textContent=item?"Редактирование сотрудника":"Добавить сотрудника";
    employeeModalSave.textContent=item?"Сохранить":"Добавить";
    employeeModalError.hidden=true;employeeModalError.textContent="";
    try{
        if(typeof positionItems==="undefined"||!positionItems.length)await loadPositions();
        if(!crewItems.length)await loadCrews();
        fillEmployeeSelects();
        employeeNameInput.value=item?.full_name||"";
        employeePositionSelect.value=item?.position_id==null?"":String(item.position_id);
        employeePhoneInput.value=item?.phone||"";
        employeeCrewSelect.value=item?.crew_id==null?"":String(item.crew_id);
        updateEmployeeDescription();updateEmployeeCrewPreview();closeAssignmentEditor();
        if(item){employeeAssignmentsSection.hidden=false;await loadEmployeeAssignments(item.id)}else{employeeAssignmentsSection.hidden=true;employeeAssignments=[]}
        employeeModal.hidden=false;setTimeout(()=>employeeNameInput.focus(),0);
    }catch(error){alert(error.message)}
}
function closeEmployeeModal(){employeeModal.hidden=true}
employeeSearchInput?.addEventListener("input",renderEmployees);
employeePositionSelect?.addEventListener("change",updateEmployeeDescription);
employeeCrewSelect?.addEventListener("change",updateEmployeeCrewPreview);
addEmployeeButton?.addEventListener("click",()=>openEmployeeModal());
employeeModalClose?.addEventListener("click",closeEmployeeModal);
employeeModalCancel?.addEventListener("click",closeEmployeeModal);
employeeModal?.addEventListener("click",e=>{if(e.target===employeeModal)closeEmployeeModal()});
employeeList?.addEventListener("click",async e=>{
    const edit=e.target.closest(".edit-employee");
    if(edit){const item=employeeItems.find(x=>x.id===Number(edit.dataset.id));if(item)await openEmployeeModal(item);return}
    const del=e.target.closest(".delete-employee");
    if(del){
        const item=employeeItems.find(x=>x.id===Number(del.dataset.id));
        if(!item||!confirm(`Удалить сотрудника «${item.full_name}»?`))return;
        try{const r=await fetch(`/api/employees/${item.id}`,{method:"DELETE"});const x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить сотрудника");await loadEmployees()}catch(error){alert(error.message)}
    }
});
addAssignmentButton?.addEventListener("click",()=>openAssignmentEditor());
assignmentCancelButton?.addEventListener("click",closeAssignmentEditor);
employeeAssignmentsList?.addEventListener("click",async e=>{const edit=e.target.closest(".edit-assignment"),del=e.target.closest(".delete-assignment");if(edit){const item=employeeAssignments.find(x=>x.id===Number(edit.dataset.id));if(item)await openAssignmentEditor(item);return}if(del){const item=employeeAssignments.find(x=>x.id===Number(del.dataset.id));if(!item||!confirm(`Удалить назначение на объект «${item.object_name}»?`))return;try{const r=await fetch(`/api/employees/${employeeEditId}/assignments/${item.id}`,{method:"DELETE"}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить назначение");await loadEmployeeAssignments(employeeEditId)}catch(err){alert(err.message)}}});
assignmentSaveButton?.addEventListener("click",async()=>{if(!employeeEditId)return;const object_id=Number(assignmentObjectSelect.value),po_id=Number(assignmentPoSelect.value),category_id=Number(assignmentCategorySelect.value);if(!object_id||!po_id||!category_id){assignmentError.textContent="Выберите объект, ПО и категорию";assignmentError.hidden=false;return}assignmentSaveButton.disabled=true;assignmentError.hidden=true;try{const url=assignmentEditId?`/api/employees/${employeeEditId}/assignments/${assignmentEditId}`:`/api/employees/${employeeEditId}/assignments`;const r=await fetch(url,{method:assignmentEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({object_id,po_id,category_id})}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить назначение");closeAssignmentEditor();await loadEmployeeAssignments(employeeEditId)}catch(err){assignmentError.textContent=err.message;assignmentError.hidden=false}finally{assignmentSaveButton.disabled=false}});

employeeModalSave?.addEventListener("click",async()=>{
    const full_name=employeeNameInput.value.trim();
    if(!full_name){employeeModalError.textContent="Введите ФИО сотрудника";employeeModalError.hidden=false;return}
    employeeModalSave.disabled=true;employeeModalError.hidden=true;
    try{
        const body={
            full_name,
            position_id:employeePositionSelect.value?Number(employeePositionSelect.value):null,
            phone:employeePhoneInput.value.trim()||null,
            crew_id:employeeCrewSelect.value?Number(employeeCrewSelect.value):null
        };
        const r=await fetch(employeeEditId?`/api/employees/${employeeEditId}`:"/api/employees",{
            method:employeeEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)
        });
        const x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить сотрудника");
        closeEmployeeModal();await loadEmployees();
    }catch(error){employeeModalError.textContent=error.message;employeeModalError.hidden=false}
    finally{employeeModalSave.disabled=false}
});

// Existing Employees navigation opens this panel; load data on first use.
employeesNavButton?.addEventListener("click",()=>loadEmployees().catch(error=>{if(employeeList)employeeList.innerHTML=`<div class="category-empty">${error.message}</div>`}));
employeesTab?.addEventListener("click",()=>loadEmployees().catch(()=>{}));


// ===== Crews page / CRUD =====
const crewsNavButton=document.getElementById("crewsNavButton");
const crewsPage=document.getElementById("crewsPage");
const backFromCrewsButton=document.getElementById("backFromCrewsButton");
const crewList=document.getElementById("crewList");
const addCrewButton=document.getElementById("addCrewButton");
const crewSearchInput=document.getElementById("crewSearchInput");
const crewCount=document.getElementById("crewCount");
const crewModal=document.getElementById("crewModal");
const crewModalTitle=document.getElementById("crewModalTitle");
const crewModalClose=document.getElementById("crewModalClose");
const crewModalCancel=document.getElementById("crewModalCancel");
const crewModalSave=document.getElementById("crewModalSave");
const crewDriverInput=document.getElementById("crewDriverInput");
const crewPhoneInput=document.getElementById("crewPhoneInput");
const crewVehicleInput=document.getElementById("crewVehicleInput");
const crewPlateInput=document.getElementById("crewPlateInput");
const crewModalError=document.getElementById("crewModalError");
let crewEditId=null;

async function refreshCrews(){
    await loadCrews();
    renderCrews();
}
function renderCrews(){
    if(!crewList)return;
    crewList.replaceChildren();
    const q=(crewSearchInput?.value||"").trim().toLocaleLowerCase("ru");
    const items=crewItems.filter(item=>!q||[
        item.driver_full_name,item.driver_phone,item.vehicle_make,item.vehicle_plate
    ].some(v=>(v||"").toLocaleLowerCase("ru").includes(q)));
    if(crewCount)crewCount.textContent=`Показано: ${items.length} из ${crewItems.length}`;
    if(!items.length){
        crewList.innerHTML='<div class="category-empty">Экипажи не найдены</div>';
        return;
    }
    const header=document.createElement("div");
    header.className="crew-table-header";
    header.innerHTML="<strong>Водитель</strong><strong>Телефон</strong><strong>Автомобиль</strong><strong>Гос. номер</strong><strong>Действия</strong>";
    crewList.append(header);
    items.forEach(item=>{
        const row=document.createElement("div");
        row.className="crew-table-row";
        row.innerHTML='<div class="crew-driver"></div><div class="crew-phone"></div><div class="crew-vehicle"></div><div class="crew-plate"></div><div class="category-actions"><button type="button" class="category-icon-button edit-crew" title="Редактировать">✎</button><button type="button" class="category-icon-button danger delete-crew" title="Удалить">🗑</button></div>';
        row.querySelector(".crew-driver").textContent=item.driver_full_name||"—";
        row.querySelector(".crew-phone").textContent=item.driver_phone||"—";
        row.querySelector(".crew-vehicle").textContent=item.vehicle_make||"—";
        row.querySelector(".crew-plate").textContent=item.vehicle_plate||"—";
        row.querySelector(".edit-crew").dataset.id=item.id;
        row.querySelector(".delete-crew").dataset.id=item.id;
        crewList.append(row);
    });
}
function openCrewModal(item=null){
    crewEditId=item?.id||null;
    crewModalTitle.textContent=item?"Редактирование экипажа":"Добавить экипаж";
    crewModalSave.textContent=item?"Сохранить":"Добавить";
    crewDriverInput.value=item?.driver_full_name||"";
    crewPhoneInput.value=item?.driver_phone||"";
    crewVehicleInput.value=item?.vehicle_make||"";
    crewPlateInput.value=item?.vehicle_plate||"";
    crewModalError.hidden=true;crewModalError.textContent="";
    crewModal.hidden=false;
    setTimeout(()=>crewDriverInput.focus(),0);
}
function closeCrewModal(){crewModal.hidden=true}

crewsNavButton?.addEventListener("click",async()=>{
    closeDetails();
    processingPage.hidden=true;
    if(objectsPage)objectsPage.hidden=true;
    if(employeesPage)employeesPage.hidden=true;
    crewsPage.hidden=false;
    setActiveNav(crewsNavButton);
    try{await refreshCrews()}
    catch(error){crewList.innerHTML=`<div class="category-empty">${error.message}</div>`}
});
backFromCrewsButton?.addEventListener("click",()=>{
    crewsPage.hidden=true;
    processingPage.hidden=false;
    setActiveNav(document.querySelector(".nav-item:first-child"));
});
crewSearchInput?.addEventListener("input",renderCrews);
addCrewButton?.addEventListener("click",()=>openCrewModal());
crewModalClose?.addEventListener("click",closeCrewModal);
crewModalCancel?.addEventListener("click",closeCrewModal);
crewModal?.addEventListener("click",e=>{if(e.target===crewModal)closeCrewModal()});

crewList?.addEventListener("click",async e=>{
    const edit=e.target.closest(".edit-crew");
    if(edit){
        const item=crewItems.find(x=>x.id===Number(edit.dataset.id));
        if(item)openCrewModal(item);
        return;
    }
    const del=e.target.closest(".delete-crew");
    if(!del)return;
    const item=crewItems.find(x=>x.id===Number(del.dataset.id));
    if(!item)return;
    const linked=employeeItems.filter(x=>x.crew_id===item.id).length;
    const extra=linked?`\n\nК этому экипажу привязано сотрудников: ${linked}. После удаления у них будет снято закрепление за экипажем.`:"";
    if(!confirm(`Удалить экипаж водителя «${item.driver_full_name||"без ФИО"}»?${extra}`))return;
    try{
        const r=await fetch(`/api/crews/${item.id}`,{method:"DELETE"});
        const x=await r.json();
        if(!r.ok)throw new Error(x.message||"Не удалось удалить экипаж");
        await refreshCrews();
        if(employeeItems.length)await loadEmployees();
    }catch(error){alert(error.message)}
});

crewModalSave?.addEventListener("click",async()=>{
    const driver_full_name=crewDriverInput.value.trim();
    if(!driver_full_name){
        crewModalError.textContent="Укажите ФИО водителя";
        crewModalError.hidden=false;
        return;
    }
    crewModalSave.disabled=true;crewModalError.hidden=true;
    try{
        const body={
            driver_full_name,
            driver_phone:crewPhoneInput.value.trim()||null,
            vehicle_make:crewVehicleInput.value.trim()||null,
            vehicle_plate:crewPlateInput.value.trim()||null
        };
        const r=await fetch(crewEditId?`/api/crews/${crewEditId}`:"/api/crews",{
            method:crewEditId?"PATCH":"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify(body)
        });
        const x=await r.json();
        if(!r.ok)throw new Error(x.message||"Не удалось сохранить экипаж");
        closeCrewModal();
        await refreshCrews();
        if(employeeItems.length)await loadEmployees();
    }catch(error){
        crewModalError.textContent=error.message;
        crewModalError.hidden=false;
    }finally{
        crewModalSave.disabled=false;
    }
});


// ===== Contractors page / CRUD =====
const contractorsNavButton=document.getElementById("contractorsNavButton");
const contractorsPage=document.getElementById("contractorsPage");
const backFromContractorsButton=document.getElementById("backFromContractorsButton");
const contractorList=document.getElementById("contractorList");
const addContractorButton=document.getElementById("addContractorButton");
const contractorSearchInput=document.getElementById("contractorSearchInput");
const contractorCount=document.getElementById("contractorCount");
const contractorModal=document.getElementById("contractorModal");
const contractorModalTitle=document.getElementById("contractorModalTitle");
const contractorModalClose=document.getElementById("contractorModalClose");
const contractorModalCancel=document.getElementById("contractorModalCancel");
const contractorModalSave=document.getElementById("contractorModalSave");
const contractorNameInput=document.getElementById("contractorNameInput");
const contractorModalError=document.getElementById("contractorModalError");
let contractorItems=[];
let contractorEditId=null;

async function loadContractors(){
    const r=await fetch("/api/contractors");
    const x=await r.json();
    if(!r.ok)throw new Error(x.message||"Не удалось загрузить подрядные организации");
    contractorItems=x.items||[];
    renderContractors();
}
function renderContractors(){
    if(!contractorList)return;
    contractorList.replaceChildren();
    const q=(contractorSearchInput?.value||"").trim().toLocaleLowerCase("ru");
    const items=contractorItems.filter(x=>!q||(x.name||"").toLocaleLowerCase("ru").includes(q));
    if(contractorCount)contractorCount.textContent=`Показано: ${items.length} из ${contractorItems.length}`;
    if(!items.length){contractorList.innerHTML='<div class="category-empty">Организации не найдены</div>';return}
    const h=document.createElement("div");h.className="contractor-table-header";h.innerHTML="<strong>Наименование</strong><strong>Действия</strong>";contractorList.append(h);
    items.forEach(item=>{
        const row=document.createElement("div");row.className="contractor-table-row";
        row.innerHTML='<div class="contractor-name"></div><div class="category-actions"><button type="button" class="category-icon-button edit-contractor" title="Редактировать">✎</button><button type="button" class="category-icon-button danger delete-contractor" title="Удалить">🗑</button></div>';
        row.querySelector(".contractor-name").textContent=item.name;
        row.querySelector(".edit-contractor").dataset.id=item.id;
        row.querySelector(".delete-contractor").dataset.id=item.id;
        contractorList.append(row);
    });
}
function openContractorModal(item=null){
    contractorEditId=item?.id||null;
    contractorModalTitle.textContent=item?"Редактирование организации":"Добавить организацию";
    contractorModalSave.textContent=item?"Сохранить":"Добавить";
    contractorNameInput.value=item?.name||"";
    contractorModalError.hidden=true;contractorModalError.textContent="";
    contractorModal.hidden=false;setTimeout(()=>contractorNameInput.focus(),0);
}
function closeContractorModal(){contractorModal.hidden=true}

contractorsNavButton?.addEventListener("click",async()=>{
    closeDetails();processingPage.hidden=true;
    if(objectsPage)objectsPage.hidden=true;
    if(employeesPage)employeesPage.hidden=true;
    if(crewsPage)crewsPage.hidden=true;
    contractorsPage.hidden=false;setActiveNav(contractorsNavButton);
    try{await loadContractors()}catch(error){contractorList.innerHTML=`<div class="category-empty">${error.message}</div>`}
});
backFromContractorsButton?.addEventListener("click",()=>{contractorsPage.hidden=true;processingPage.hidden=false;setActiveNav(document.querySelector(".nav-item:first-child"))});
contractorSearchInput?.addEventListener("input",renderContractors);
addContractorButton?.addEventListener("click",()=>openContractorModal());
contractorModalClose?.addEventListener("click",closeContractorModal);
contractorModalCancel?.addEventListener("click",closeContractorModal);
contractorModal?.addEventListener("click",e=>{if(e.target===contractorModal)closeContractorModal()});

contractorList?.addEventListener("click",async e=>{
    const edit=e.target.closest(".edit-contractor");
    if(edit){const item=contractorItems.find(x=>x.id===Number(edit.dataset.id));if(item)openContractorModal(item);return}
    const del=e.target.closest(".delete-contractor");
    if(!del)return;
    const item=contractorItems.find(x=>x.id===Number(del.dataset.id));
    if(!item||!confirm(`Удалить организацию «${item.name}»?`))return;
    try{
        const r=await fetch(`/api/contractors/${item.id}`,{method:"DELETE"});
        const x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить организацию");
        await loadContractors();
    }catch(error){alert(error.message)}
});
contractorModalSave?.addEventListener("click",async()=>{
    const name=contractorNameInput.value.trim();
    if(!name){contractorModalError.textContent="Укажите наименование организации";contractorModalError.hidden=false;return}
    contractorModalSave.disabled=true;contractorModalError.hidden=true;
    try{
        const r=await fetch(contractorEditId?`/api/contractors/${contractorEditId}`:"/api/contractors",{
            method:contractorEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})
        });
        const x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить организацию");
        closeContractorModal();await loadContractors();
    }catch(error){contractorModalError.textContent=error.message;contractorModalError.hidden=false}
    finally{contractorModalSave.disabled=false}
});
