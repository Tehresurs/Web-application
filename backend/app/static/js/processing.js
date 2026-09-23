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
const pageSize=document.getElementById('pageSize');
const recordsInfo=document.getElementById('recordsInfo');
const pageButtons=document.getElementById('pageButtons');
const clearResultsButton=document.getElementById('clearResultsButton');
const refreshButton=document.getElementById('refreshButton');
const downloadHtmlButton=document.getElementById('downloadHtmlButton');
let currentPage=1;
window.processingReports = [];
let checkedPath = null;
let closeDetailsTimer;

folderPath.addEventListener("input", () => {
    checkedPath = null;
    parseButton.disabled = true;
    folderInfo.textContent = "Папка ещё не проверена";
    folderInfo.className = "folder-info";
});

checkFolderButton.addEventListener("click", async () => {
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
});

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
pageSize.addEventListener("change", renderReports);
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

function openDetails(report) {
    clearTimeout(closeDetailsTimer);
    setDetailsValue("detailsFile", report.filename);
    setDetailsValue("detailsEmployee", report.full_name);
    setDetailsValue("detailsPosition", report.position);
    setDetailsValue("detailsDate", report.report_date);
    setDetailsValue("detailsObject", report.object_name);
    setDetailsValue("detailsGeneralContractor", report.general_contractor);
    setDetailsValue("detailsSubcontractor", report.subcontractor);

    const databaseStatus = document.getElementById("databaseStatus");
    databaseStatus.className = "database-status";

    if (report.object_status === "new") {
        document.getElementById("detailsTitle").textContent = "Новый объект";
        databaseStatus.textContent = "Объект отсутствует в базе данных.";
        databaseStatus.classList.add("warning");
        newObjectSection.hidden = false;
        addObjectButton.hidden = false;
        document.getElementById("newObjectName").value = report.object_name || "";
    } else if (report.object_status === "similar") {
        document.getElementById("detailsTitle").textContent = "Требуется согласование";
        databaseStatus.textContent = "Найден похожий объект. Требуется решение пользователя.";
        databaseStatus.classList.add("warning");
        newObjectSection.hidden = true;
        addObjectButton.hidden = true;
    } else if (report.object_status === "found") {
        document.getElementById("detailsTitle").textContent = "Результат проверки";
        databaseStatus.textContent = "Объект найден в базе данных.";
        databaseStatus.classList.add("ok");
        newObjectSection.hidden = true;
        addObjectButton.hidden = true;
    } else {
        document.getElementById("detailsTitle").textContent = "Ошибка проверки";
        databaseStatus.textContent = "Объект не распознан или проверка не выполнена.";
        databaseStatus.classList.add("error");
        newObjectSection.hidden = true;
        addObjectButton.hidden = true;
    }

    if (report.problems?.length) {
        databaseStatus.textContent += " " + report.problems.join(". ") + ".";
    }
    document.getElementById("objectCategory").value = "";
    document.getElementById("objectPo").selectedIndex = -1;
    document.getElementById("objectComment").value = "";

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

    openDetails(report);
});
