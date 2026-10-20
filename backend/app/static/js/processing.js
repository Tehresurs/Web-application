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
const exportExcelButton=document.getElementById('exportExcelButton');
window.processingReports = [];
let checkedPath = null;
let closeDetailsTimer;
let activeReportIndex = null;
const processingLogs = [];
const reportSaver = new BatchReportSaveController({
    getReports: () => window.matrixActiveReport ? [window.matrixActiveReport] : window.processingReports,
    button: document.getElementById("saveResultButton"),
    retryButton: document.getElementById("checkSaveResultButton"),
    message: document.getElementById("saveResultMessage"),
    fetchRequest: (...args) => fetch(...args),
    ready: report => {
        if (report.review_options?.enabled) return reportReviewIssues(report).length === 0;
        if (getFinalReportStatus(report) !== "verified" || !report.report_date ||
            !report.employee_id || !(report.entity_id || report.object_id) || !report.assignments_verified ||
            (report.subcontractor && !report.subcontractor_id) ||
            (report.problems || []).length) return false;
        const poIds = [report.general_contractor_id];
        return poIds.every(poId => {
            const item = report.assignments?.[poId];
            return poId && item?.id && item.category_id &&
                Number(item.employee_id) === Number(report.employee_id) &&
                (report.entity_id ? Number(item.entity_id) === Number(report.entity_id) : Number(item.object_id) === Number(report.object_id)) && Number(item.po_id) === Number(poId);
        });
    },
    onState: saving => {
        document.querySelector('.details-content').inert = saving;
        document.querySelector('.app').inert = saving;
    },
});

function addProcessingLog(level, message) {
    processingLogs.push({time: new Date().toLocaleString("ru-RU"), level, message});
    if (processingLogs.length > 1000) processingLogs.shift();
    renderProcessingLogs();
}

function renderProcessingLogs() {
    const table = document.getElementById("logsTable");
    table.replaceChildren();
    if (!processingLogs.length) {
        const cell = document.createElement("td");
        cell.colSpan = 3;
        cell.textContent = "Записей пока нет. Запустите проверку отчётов.";
        const row = document.createElement("tr");
        row.append(cell);
        table.append(row);
        return;
    }
    processingLogs.slice().reverse().forEach(entry => {
        const row = document.createElement("tr");
        [entry.time, entry.level, entry.message].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.append(cell);
        });
        table.append(row);
    });
}

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
        addProcessingLog("Ошибка", folderInfo.textContent);
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

function getFinalReportStatus(report) {
    if (report.review_options?.enabled) {
        if (Object.keys(report.alias_conflicts || {}).length) return 'needs_approval';
        if (reviewBaseProblems(report).some(p=>/дат|не удалось обработать/i.test(p))) return 'error';
        const fields=['employee','object','general_contractor','subcontractor'];
        return fields.every(f=>reviewApproved(report,f)||report[`${f}_status`]==='found') ? 'verified' : 'needs_approval';
    }
    if (Object.keys(report.alias_conflicts || {}).length) return "needs_approval";
    if (report.status === "error") return "error";

    const statuses = [
        report.employee_status,
        report.object_status,
        report.general_contractor_status,
    ];

    // Пустой субподрядчик не мешает завершению проверки.
    if (report.subcontractor) {
        statuses.push(report.subcontractor_status);
    }

    if (statuses.includes("similar")) return "needs_approval";
    if (statuses.includes("new")) return "has_new";

    const complete = statuses.every(status => status === "found");
    return complete ? "verified" : "attention";
}

function buildStatus(report) {
    const badge = document.createElement("span");
    const finalStatus = getFinalReportStatus(report);

    const view = {
        error: ["error", "Ошибка"],
        needs_approval: ["warning", "Требует согласования"],
        has_new: ["warning", "Есть новые данные"],
        verified: ["ok", "✓ Проверен"],
        attention: ["warning", "Требует внимания"],
    };

    const [status, label] = view[finalStatus] || view.attention;
    badge.className = `status-badge ${status}`;
    badge.textContent = label;
    if(report.review_options?.enabled && reportReviewIssues(report).length){badge.className='status-badge warning';badge.textContent=reportReviewIssues(report).includes('Нет категории')?'Нет категории':'Требует согласования';}
    return badge;
}

function renderReports() {
    updateExportButtons();
    resultTable.replaceChildren();
    const query = searchInput.value.trim().toLocaleLowerCase("ru");
    window.processingReports.forEach((report, index) => {
        if(window.matrixActiveReport && report!==window.matrixActiveReport)return;
        if (query && ![report.filename, report.full_name, report.object_name]
            .some(value => (value || "").toLocaleLowerCase("ru").includes(query))) return;
        if (dateFilter.value !== "all" && report.report_date !== dateFilter.value) return;
        if (statusFilter.value === "problem" && (report.review_options?.enabled ? reportReviewIssues(report).length===0 : getFinalReportStatus(report) === "verified")) return;
        if (statusFilter.value === "new" && getFinalReportStatus(report) !== "has_new") return;
        if (statusFilter.value === "ok" && (report.review_options?.enabled ? reportReviewIssues(report).length>0 : getFinalReportStatus(report) !== "verified")) return;
        if (statusFilter.value === "error" && getFinalReportStatus(report) !== "error") return;
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
        const issues=report.review_options?.enabled ? reportReviewIssues(report) : report.problems || [];
        statusCell.title = issues.join("; ");
        statusCell.append(buildStatus(report));
        if(issues.length){const remarks=document.createElement('div');remarks.className='review-list-issues';remarks.textContent=issues.join('; ');statusCell.append(remarks);}
        row.append(statusCell);
        const action = document.createElement("td");
        const button = document.getElementById("viewButtonTemplate")
            .content.firstElementChild.cloneNode(true);
        button.dataset.reportIndex = index;
        action.append(button);
        row.append(action);
        resultTable.append(row);
    });
    if(window.processingReports.some(r=>r.review_options?.enabled)){
        const reports=window.processingReports;
        updateStatistics({total:reports.length,ok:reports.filter(r=>r.control_saved||reportReviewIssues(r).length===0).length,
            warning:reports.filter(r=>getFinalReportStatus(r)!=='error'&&reportReviewIssues(r).length>0).length,
            error:reports.filter(r=>getFinalReportStatus(r)==='error').length});
    }
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
clearResultsButton.addEventListener("click",()=>{window.matrixActiveReport=null;document.getElementById("matrixSingleReportPanel")?.setAttribute("hidden","");window.processingReports=[];document.querySelectorAll(".stat-number").forEach(n=>n.textContent="—");renderReports();downloadHtmlButton.disabled=true;});
function canExportReports() {
    return window.processingReports.length > 0 && window.processingReports.every(report => {
        if(report.review_options?.enabled)return reportReviewIssues(report).length===0;
        if (getFinalReportStatus(report) !== "verified" || !report.assignments_verified) return false;
        if (!report.employee_id || !(report.entity_id || report.object_id) || !report.general_contractor_id) return false;
        const poIds = [report.general_contractor_id];
        return poIds.every(poId => {
            const assignment = report.assignments?.[poId];
            return poId && assignment?.id && assignment.category_id &&
                Number(assignment.employee_id) === Number(report.employee_id) &&
                (report.entity_id ? Number(assignment.entity_id) === Number(report.entity_id) : Number(assignment.object_id) === Number(report.object_id)) &&
                Number(assignment.po_id) === Number(poId);
        });
    });
}

async function verifyReportAssignments(reports) {
    const byEmployee = new Map();
    for (const report of reports) {
        if (getFinalReportStatus(report) !== "verified") continue;
        try {
            if (!byEmployee.has(report.employee_id)) {
                const response = await fetch(report.review_options?.enabled ? `/api/daily-control-results/review-assignments/${report.employee_id}` : `/api/employees/${report.employee_id}/assignments`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
                byEmployee.set(report.employee_id, data.items || []);
            }
            const assignments = {};
            for (const po of await getReportAssignmentPoEntries(report)) {
                const matches = byEmployee.get(report.employee_id).filter(item => (report.entity_id ? Number(item.entity_id) === Number(report.entity_id) : Number(item.object_id) === Number(report.object_id)) && Number(item.po_id) === po.id);
                if (matches.length === 1) assignments[po.id] = matches[0];
            }
            report.assignments = assignments;
            report.assignment_key = `${report.employee_id}:${report.entity_id ? `entity:${report.entity_id}` : report.object_id}:${report.general_contractor_id}`;
            report.assignments_verified = true;
        } catch (error) {
            report.assignments_verified = false;
            addProcessingLog("Ошибка", `${report.filename}: проверка назначений — ${error.message}`);
        }
    }
    updateExportButtons();
}

function updateExportButtons() {
    reportSaver.sync();
    const ready = canExportReports();
    [downloadHtmlButton, exportExcelButton].forEach(button => {
        button.disabled = !ready;
        button.title = ready ? "Скачать все согласованные отчёты" : "Согласуйте все отчёты и выберите сохранённые назначения с категориями";
    });
    document.getElementById("exportHint").textContent = ready
        ? "Все отчёты согласованы. Скачивание доступно."
        : !window.processingReports.length ? "Сначала обработайте отчёты."
        : "Скачивание заблокировано. Проверьте данные и назначения через 👁: " + window.processingReports.filter(report =>
            getFinalReportStatus(report) !== "verified" || !report.assignments_verified ||
            !report.assignments?.[report.general_contractor_id]
        ).map(report => report.filename).join("; ");
}

function getExportTable() {
    const headers = ["Файл", "Инженер", "Должность", "Дата отчёта", "Объект", "Генподрядчик", "Субподрядчик", "ПО назначения", "Категория", "ID назначения"];
    const rows = window.processingReports.flatMap(report =>
        [report.review_options?.enabled && reviewApproved(report,'general_contractor') ? null : report.general_contractor_id].map(poId => {
            const assignment = report.assignments[poId];
            return [report.filename, report.resolved_employee?.name || report.full_name,
                report.position, report.report_date, report.resolved_object?.name || report.object_name,
                report.resolved_general_contractor?.name || report.general_contractor,
                report.resolved_subcontractor?.name || report.subcontractor,
                assignment.po_name || (Number(poId) === Number(report.general_contractor_id)
                    ? report.resolved_general_contractor?.name || report.general_contractor
                    : report.resolved_subcontractor?.name || report.subcontractor),
                assignment.category_name, assignment.id];
        })
    );
    return {headers, rows};
}

function escapeExportText(value) {
    return String(value ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
        .replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&apos;"}[char]));
}

async function downloadReport(format) {
    updateExportButtons();
    if (!canExportReports()) return;
    const {headers, rows} = getExportTable();
    let content;
    if (format === "html") {
        const row = (values, tag) => `<tr>${values.map(value => `<${tag}>${escapeExportText(value)}</${tag}>`).join("")}</tr>`;
        content = `<!doctype html><html lang="ru"><meta charset="utf-8"><title>Согласованные отчёты</title><style>body{font-family:Arial}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:8px;text-align:left}</style><h1>Согласованные отчёты</h1><table><thead>${row(headers,"th")}</thead><tbody>${rows.map(values => row(values,"td")).join("")}</tbody></table></html>`;
    } else {
        // Excel XML: explicit String cells preserve dates, phone numbers and prevent formula execution.
        content = '<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>' +
            '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Отчёты"><Table>' +
            [headers, ...rows].map(values => '<Row>' + values.map(value => `<Cell><Data ss:Type="String">${escapeExportText(value)}</Data></Cell>`).join("") + '</Row>').join("") +
            '</Table></Worksheet></Workbook>';
    }
    const blob = new Blob([content], {type: format === "html" ? "text/html;charset=utf-8" : "application/xml;charset=utf-8"});
    const filename = `reports-${new Date().toISOString().slice(0,10)}.${format === "html" ? "html" : "xml"}`;
    const hint = document.getElementById("exportHint");
    if (typeof window.showSaveFilePicker === "function") {
        try {
            const handle = await window.showSaveFilePicker({suggestedName: filename});
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
            hint.textContent = `Файл сохранён: ${handle.name}`;
            addProcessingLog("Информация", hint.textContent);
        } catch (error) {
            hint.textContent = error.name === "AbortError" ? "Сохранение отменено. Можно повторить скачивание."
                : `Не удалось сохранить файл: ${error.message}`;
            if (error.name !== "AbortError") addProcessingLog("Ошибка", hint.textContent);
        }
        return;
    }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    hint.textContent = `Скачивание ${filename} передано браузеру. Проверьте список загрузок (Ctrl+J).`;
    setTimeout(() => { link.remove(); URL.revokeObjectURL(url); }, 60000);
}

downloadHtmlButton.addEventListener("click", () => downloadReport("html"));
exportExcelButton.addEventListener("click", () => downloadReport("excel"));
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
    window.matrixActiveReport=null;document.getElementById('matrixSingleReportPanel')?.setAttribute('hidden','');
    window.processingReports = [];
    renderReports();
    document.querySelectorAll(".stat-number").forEach(node => { node.textContent = "—"; });
    folderInfo.className = "folder-info";
    folderInfo.textContent = "Обрабатываем отчёты...";
    addProcessingLog("Информация", `Начата проверка папки: ${path}`);
    try {
        const response = await fetch("/api/process-folder", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({path}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "Ошибка обработки отчётов");
        window.processingReports = attachReportSourcePaths([
            ...result.reports,
            ...(result.processing_errors || []).map(error => ({
                filename: error.filename,
                status: "error",
                employee_status: "not_checked",
                object_status: "not_checked",
                problems: [error.error || "Не удалось обработать файл"],
            })),
        ], path);
        for(const report of window.processingReports) await loadReportReviewOptions(report);
        updateStatistics(result);
        dateFilter.innerHTML='<option value="all">Все даты</option>';
        [...new Set(window.processingReports.map(r=>r.report_date).filter(Boolean))].sort().reverse().forEach(d=>{const o=document.createElement("option");o.value=d;o.textContent=d;dateFilter.append(o)});
        document.getElementById("lastCheck").textContent="Последняя проверка: "+new Intl.DateTimeFormat("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date());
        renderReports();
        folderInfo.textContent = `Проверка завершена. Отчётов: ${result.total}`;
        await verifyReportAssignments(window.processingReports);
        renderReports();
        window.processingReports.forEach(report => {
            if (["subobject_exact", "subobject_alias"].includes(report.object_match_source)) {
                const event = report.object_match_source === "subobject_exact" ? "SUBOBJECT_EXACT_MATCH" : "SUBOBJECT_ALIAS_MATCH";
                addProcessingLog("Информация", `${event}: «${report.object_name}» → subobject_id=${report.subobject_id} → object_id=${report.object_id}`);
            }
            addProcessingLog(report.status === "error" ? "Ошибка" : report.status === "warning" ? "Внимание" : "Информация",
                `${report.filename}: ${(report.problems || []).join("; ") || "Проверка завершена"}`);
        });
        addProcessingLog("Информация", folderInfo.textContent);
        folderInfo.className = "folder-info success";
    } catch (error) {
        folderInfo.textContent = error.message || "Ошибка соединения с сервером";
        addProcessingLog("Ошибка", folderInfo.textContent);
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

function getCandidateEntity(candidate) {
    return candidate?.subobject || candidate?.employee || candidate?.object || candidate?.po || candidate || {};
}

function getCandidateName(candidate) {
    const entity = getCandidateEntity(candidate);
    return entity.full_name || entity.name || "—";
}

function getCandidateId(candidate) {
    return getCandidateEntity(candidate).id ?? null;
}

function recalculateReportStatus(report) {
    const finalStatus = getFinalReportStatus(report);
    report.status = finalStatus === "error"
        ? "error"
        : finalStatus === "verified"
            ? "ok"
            : "warning";
}

function confirmCandidate(report, config, candidate) {
    report.server_problems=[];
    const id = getCandidateId(candidate);
    const name = getCandidateName(candidate);

    if (config.idField) report[config.idField] = id;
    report[config.statusField] = "found";
    report[config.resolvedField] = {id, name};
    if (config.kind === "subcontractor") addProcessingLog("Информация", `SUBCONTRACTOR_SELECTED: «${report[config.parsedField]}» → target_id=${id}`);
    if (config.kind === "object") {
        const child = candidate.entity_kind === "subobject";
        report.entity_id = candidate.entity_id ?? candidate.current_hierarchy?.entity_id ?? null;
        report.current_hierarchy = candidate.current_hierarchy ?? null;
        report.subobject_id = child ? candidate.subobject_id : null;
        report.subobject_name = child ? candidate.subobject_name : null;
        report.resolved_subobject = child ? {id: candidate.subobject_id, name: candidate.subobject_name} : null;
        report.object_id = child ? candidate.object_id : id;
        report.resolved_object = child ? {id: candidate.object_id, name: candidate.object_name} : {id, name};
        report.object_match_source = child ? "subobject_selected" : "selected";
        if (report.entity_id) {
            const h = report.current_hierarchy || {};
            report.object_id = null;
            report.subobject_id = null;
            report.resolved_object = {id: null, name: h.parent?.name || h.name || name};
            report.resolved_subobject = h.parent_entity_id != null ? {id: null, name: h.name || name} : null;
            report.subobject_name = report.resolved_subobject?.name ?? null;
        }
        report.assignments_verified = false;
        if (child) addProcessingLog("Информация", `SUBOBJECT_SELECTED: «${report.object_name}» → subobject_id=${report.subobject_id} → object_id=${report.object_id}`);
    }

    if (Array.isArray(report.problems)) {
        report.problems = report.problems.filter(problem => {
            const value = String(problem || "").toLocaleLowerCase("ru");
            return !(config.problemWords || []).some(word => value.includes(word));
        });
    }

    recalculateReportStatus(report);
    renderReports();
    openDetails(report);
}


async function confirmAndRemember(report, config, candidate, remember) {
    const sourceValue = report[config.parsedField];
    const targetId = getCandidateId(candidate);
    const aliasKey = config.statusField.replace(/_status$/, "");
    const endpoint = "/api/value-aliases";
    const payload = {
        entity_type: config.kind === "object" && candidate.entity_kind === "subobject" ? "subobject" : config.kind,
        source_value: sourceValue,
        target_id: targetId,
    };
    if(config.kind==='object' && candidate.entity_id && candidate.current_hierarchy){
        const h=candidate.current_hierarchy;
        payload.entity_type=h.legacy_subobject_id!=null?'subobject':'object';
        payload.target_id=h.legacy_subobject_id??h.legacy_object_id;
    }
    report.alias_conflicts ||= {};
    report.alias_pending ||= {};
    report.alias_messages ||= {};
    delete report.alias_messages[aliasKey];
    if (remember) report.alias_pending[aliasKey] = true;
    if (remember) report.alias_conflicts[aliasKey] = "Соответствие сохраняется…";
    confirmCandidate(report, config, candidate);
    if (!remember) return;
    try {
        await apiPost(endpoint, payload);
        delete report.alias_conflicts[aliasKey];
        report.alias_messages[aliasKey] = "Выбор применён. Соответствие сохранено.";
        recalculateReportStatus(report);
        renderReports();
    } catch (error) {
        console.error("ALIAS_SAVE_FAILED", {
            status: error.status ?? null, endpoint, response_body: error.responseBody ?? error.message,
            entity_type: payload.entity_type, target_id: targetId,
        });
        report.alias_conflicts[aliasKey] = error.status === 409
            ? "Для этого значения уже сохранено другое соответствие."
            : "Выбор применён к текущему отчёту, но сохранить соответствие не удалось.";
        recalculateReportStatus(report);
        renderReports();
    } finally {
        delete report.alias_pending[aliasKey];
        if (typeof activeReportIndex !== "undefined" && window.processingReports?.[activeReportIndex] === report) openDetails(report);
    }
}


async function apiPost(url, payload) {
    const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
    });

    const responseBody = await response.text();
    let data = {};
    try { data = JSON.parse(responseBody); } catch (_) {}

    if (!response.ok) {
        const error = new Error(data.message || data.detail || `HTTP ${response.status}`);
        error.status = response.status;
        error.endpoint = url;
        error.responseBody = responseBody;
        throw error;
    }
    return data;
}

async function resolvePositionId(positionName) {
    if (!positionName) return null;

    const response = await fetch("/api/positions");
    if (!response.ok) return null;

    const data = await response.json();
    const normalized = String(positionName).trim().toLocaleLowerCase("ru");

    const exact = (data.items || []).find(item =>
        String(item.name || "").trim().toLocaleLowerCase("ru") === normalized
    );

    return exact?.id ?? null;
}

async function addNewDatabaseItem(report, config, button, message) {
    const sourceValue = report[config.parsedField];
    if (!sourceValue) return;

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Добавление...";

    try {
        let result;
        let id = null;
        let name = sourceValue;

        if (config.kind === "employee") {
            const positionId = await resolvePositionId(report.position);
            result = await apiPost("/api/employees", {
                full_name: sourceValue,
                position_id: positionId,
                phone: null,
                crew_id: null,
            });
            id = result.id ?? null;
        } else if (config.kind === "object") {
            result = await apiPost("/api/objects", {name: sourceValue});
            id = result.object?.id ?? result.id ?? null;
            name = result.object?.name || sourceValue;
        } else if (config.kind === "po" || config.kind === "subcontractor") {
            result = await apiPost("/api/po-types", {name: sourceValue});
            id = result.item?.id ?? result.id ?? null;
            name = result.item?.name || sourceValue;
        } else {
            throw new Error("Неизвестный тип справочника");
        }

        if (config.idField) report[config.idField] = id;
        report[config.statusField] = "found";
        report[config.resolvedField] = {id, name, added: true};
        if (config.kind === "subcontractor") addProcessingLog("Информация", `SUBCONTRACTOR_CREATED: «${name}» → target_id=${id}`);
        if (config.kind === "object") {
            report.entity_id = result.object?.entity_id ?? result.item?.entity_id ?? null;
            report.current_hierarchy = result.object?.current_hierarchy ?? result.item?.current_hierarchy ?? null;
            report.subobject_id = null;
            report.subobject_name = null;
            report.resolved_subobject = null;
            report.object_match_source = "created";
        }

        if (Array.isArray(report.problems)) {
            report.problems = report.problems.filter(problem => {
                const value = String(problem || "").toLocaleLowerCase("ru");
                return !(config.problemWords || []).some(word => value.includes(word));
            });
        }

        recalculateReportStatus(report);
        renderReports();
        openDetails(report);
    } catch (error) {
        button.disabled = false;
        button.textContent = originalText;
        message.textContent = `Ошибка: ${error.message}`;
    }
}

function buildSubobjectEditor(report, config) {
    const container = document.createElement("div");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = "Добавить как подобъект";
    container.append(button);
    button.addEventListener("click", async () => {
        button.disabled = true;
        const form = document.createElement("form");
        form.style.display = "grid";
        form.style.gap = "8px";
        form.style.marginTop = "10px";
        const title = document.createElement("strong");
        title.textContent = "НОВЫЙ ПОДОБЪЕКТ";
        const nameLabel = document.createElement("label");
        nameLabel.textContent = "Название: ";
        const name = document.createElement("input");
        name.required = true;
        name.value = report.object_name || "";
        nameLabel.append(name);
        const search = document.createElement("input");
        search.placeholder = "Поиск родительского объекта";
        search.setAttribute("aria-label", "Поиск родительского объекта");
        const parentLabel = document.createElement("label");
        parentLabel.textContent = "Родительский объект: ";
        const parent = document.createElement("select");
        parent.required = true;
        parentLabel.append(parent);
        const save = document.createElement("button");
        save.type = "submit";
        save.className = "secondary-button";
        save.textContent = "Сохранить подобъект";
        save.disabled = true;
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "secondary-button";
        cancel.textContent = "Отмена";
        const message = document.createElement("small");
        form.append(title, nameLabel, search, parentLabel, save, cancel, message);
        container.append(form);
        cancel.addEventListener("click", () => { form.remove(); button.disabled = false; });
        let objects = [];
        const populate = () => {
            const selected = parent.value;
            parent.replaceChildren(new Option("Выберите родительский объект", ""));
            const query = search.value.toLocaleLowerCase("ru");
            for (const item of ConstructionChoices.parents(objects).filter(item => item.name.toLocaleLowerCase("ru").includes(query))) {
                parent.add(new Option(item.name, ConstructionChoices.value(item)));
            }
            parent.value = [...parent.options].some(option => option.value === selected) ? selected : "";
        };
        search.addEventListener("input", populate);
        try {
            const response = await fetch("/api/objects");
            if (!response.ok) throw new Error("Не удалось загрузить объекты");
            objects = (await response.json()).items || [];
            populate();
            save.disabled = false;
        } catch (error) { message.textContent = error.message; }
        form.addEventListener("submit", async event => {
            event.preventDefault();
            if (save.disabled || !parent.value || !name.value.trim()) return;
            save.disabled = true;
            cancel.disabled = true;
            try {
                const result = await apiPost("/api/subobjects", {...ConstructionChoices.reference(parent.value, true), name: name.value});
                const item = result.item;
                addProcessingLog("Информация", `SUBOBJECT_CREATED: «${item.name}» → subobject_id=${item.id} → object_id=${item.object_id}`);
                confirmCandidate(report, config, {entity_kind: "subobject", subobject: item,
                    entity_id: item.entity_id, current_hierarchy: item.current_hierarchy,
                    subobject_id: item.id, subobject_name: item.name, object_id: item.object_id, object_name: item.object_name});
            } catch (error) {
                message.textContent = `Не удалось сохранить подобъект: ${error.message}`;
                save.disabled = false;
                cancel.disabled = false;
            }
        });
    });
    return container;
}


function buildCheckRow(report, config) {
    const status = report[config.statusField] || "not_checked";
    const parsedValue = report[config.parsedField];
    const candidates = report[config.candidatesField] || [];
    const resolved = report[config.resolvedField];

    const row = document.createElement("div");
    row.style.padding = "12px 0";
    row.style.borderBottom = "1px solid rgba(148, 163, 184, .25)";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.justifyContent = "space-between";
    header.style.gap = "12px";
    header.style.alignItems = "center";

    const title = document.createElement("strong");
    title.textContent = config.label;
    header.append(title);

    const badge = document.createElement("span");
    const labels = {
        found: resolved?.match_source === "alias" ? "ИЗВЕСТНОЕ СООТВЕТСТВИЕ" : resolved?.added ? "ДОБАВЛЕНО" : resolved ? "СОГЛАСОВАНО" : "НАЙДЕНО",
        similar: "ПОХОЖЕЕ",
        new: "НОВОЕ",
        not_checked: "НЕ УКАЗАНО",
        not_applicable: "ОТСУТСТВУЕТ",
    };
    badge.textContent = labels[status] || "НЕ ПРОВЕРЕНО";
    if (config.kind === "object" && status === "found" && report.subobject_id) {
        badge.textContent = report.object_match_source === "subobject_alias" ? "ИЗВЕСТНОЕ СООТВЕТСТВИЕ ПОДОБЪЕКТА"
            : report.object_match_source === "subobject_exact" ? "ПОДОБЪЕКТ НАЙДЕН" : "ПОДОБЪЕКТ СОГЛАСОВАН";
    }
    badge.className = `status-badge ${status === "found" ? "ok" : ["not_checked", "not_applicable"].includes(status) ? "" : status === "similar" || status === "new" ? "warning" : "error"}`;
    header.append(badge);
    row.append(header);

    const value = document.createElement("div");
    value.style.marginTop = "6px";
    value.textContent = resolved?.match_source === "alias" ? `Из отчёта: ${parsedValue || "—"}` : parsedValue || "—";
    row.append(value);
    if(report.review_options?.enabled && reviewAbsenceControls(report,config,row))return row;
    if(report.review_options?.enabled && status!=='found'){
        const problem=document.createElement('small');problem.className='review-field-error';
        problem.textContent=`${config.label}: требуется сопоставление`;row.append(problem);
    }
    const aliasKey = config.statusField.replace(/_status$/, "");
    if (report.alias_messages?.[aliasKey]) {
        const message = document.createElement("small");
        message.setAttribute("role", "status");
        message.textContent = report.alias_messages[aliasKey];
        row.append(message);
    }
    if (report.alias_conflicts?.[aliasKey]) {
        const warning = document.createElement("small");
        warning.textContent = report.alias_conflicts[aliasKey];
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.className = "secondary-button";
        dismiss.textContent = "Не запоминать соответствие, подтвердить выбор для отчёта";
        dismiss.disabled = Boolean(report.alias_pending?.[aliasKey]);
        dismiss.addEventListener("click", () => {
            delete report.alias_conflicts[aliasKey];
            recalculateReportStatus(report);
            renderReports();
            openDetails(report);
        });
        row.append(warning, dismiss);
    }
    if (config.kind === "object" && report.subobject_id) {
        value.textContent = `Из отчёта: ${parsedValue || "—"}`;
        const parent = document.createElement("div");
        parent.textContent = `Родительский объект (справочно): ${report.resolved_object?.name || "—"}`;
        const child = document.createElement("div");
        child.textContent = `Объект / Подобъект: ${report.resolved_subobject?.name || report.subobject_name || "—"}`;
        row.append(child, parent);
    }
    if (config.kind === "object" && ["similar", "new"].includes(status)) {
        row.append(buildSubobjectEditor(report, config));
    }

    if (resolved) {
        const note = document.createElement("small");
        note.style.display = "block";
        note.style.marginTop = "6px";
        note.textContent = resolved.match_source === "alias" ? `Определено: ${resolved.name}` : resolved.added ? `Добавлено в базу: ${resolved.name}` : `Выбрано из базы: ${resolved.name}`;
        row.append(note);
    } else if (status === "found") {
        const note = document.createElement("small");
        note.textContent = "Совпадение найдено в базе данных.";
        row.append(note);
    } else if (status === "similar" && candidates.length) {
        const note = document.createElement("small");
        note.style.display = "block";
        note.style.marginTop = "6px";
        note.textContent = "Выберите правильную запись из базы:";
        row.append(note);

        const choices = document.createElement("div");
        choices.style.display = "grid";
        choices.style.gap = "8px";
        choices.style.marginTop = "8px";
        const groupName = `match-${activeReportIndex}-${config.statusField}`;

        candidates.forEach((candidate, index) => {
            const option = document.createElement("label");
            option.style.display = "flex";
            option.style.alignItems = "flex-start";
            option.style.gap = "8px";
            option.style.cursor = "pointer";

            const radio = document.createElement("input");
            radio.type = "radio";
            radio.name = groupName;
            radio.value = String(index);

            const caption = document.createElement("span");
            const score = typeof candidate.similarity === "number"
                ? ` — ${Math.round(candidate.similarity * 100)}%`
                : "";
            caption.textContent = getCandidateName(candidate) + score;
            if (config.kind === "object") {
                caption.textContent = candidate.entity_kind === "subobject"
                    ? `ПОДОБЪЕКТ: ${candidate.subobject_name}${score} · Родитель: ${candidate.object_name}`
                    : `ОБЪЕКТ: ${getCandidateName(candidate)}${score}`;
            }

            option.append(radio, caption);
            choices.append(option);
        });

        const actions = document.createElement("div");
        actions.style.display = "flex";
        actions.style.gap = "10px";
        actions.style.flexWrap = "wrap";
        actions.style.marginTop = "10px";

        const confirmButton = document.createElement("button");
        confirmButton.type = "button";
        confirmButton.className = "secondary-button";
        confirmButton.textContent = "Выбрать и заменить";
        confirmButton.disabled = true;

        const addAsNewButton = document.createElement("button");
        addAsNewButton.type = "button";
        addAsNewButton.className = "secondary-button";
        addAsNewButton.textContent = "Добавить как новый";

        const message = document.createElement("small");
        message.style.display = "block";
        message.style.width = "100%";
        message.style.marginTop = "6px";

        choices.addEventListener("change", () => {
            confirmButton.disabled = !choices.querySelector('input[type="radio"]:checked');
        });

        const rememberLabel = document.createElement("label");
        const rememberCheckbox = document.createElement("input");
        rememberCheckbox.type = "checkbox";
        rememberLabel.append(rememberCheckbox, document.createTextNode(" Запомнить соответствие"));

        confirmButton.addEventListener("click", () => {
            const selected = choices.querySelector('input[type="radio"]:checked');
            if (!selected) return;
            const candidate = candidates[Number(selected.value)];
            if (candidate) {
                confirmButton.disabled = true;
                confirmAndRemember(report, config, candidate, rememberCheckbox.checked);
            }
        });

        addAsNewButton.addEventListener("click", () => {
            addNewDatabaseItem(report, config, addAsNewButton, message);
        });

        actions.append(confirmButton, addAsNewButton, message);
        row.append(choices, rememberLabel, actions);
    } else if (status === "similar") {
        const note = document.createElement("small");
        note.textContent = "Найдено похожее значение, но варианты для выбора не получены.";
        row.append(note);
    } else if (status === "new") {
        const note = document.createElement("small");
        note.style.display = "block";
        note.textContent = "Такой записи в базе данных нет.";
        row.append(note);

        if (config.kind === "employee" && report.position) {
            const positionNote = document.createElement("small");
            positionNote.style.display = "block";
            positionNote.style.marginTop = "6px";
            positionNote.textContent = `Должность из отчёта: ${report.position}`;
            row.append(positionNote);
        }

        const message = document.createElement("small");
        message.style.display = "block";
        message.style.marginTop = "6px";

        const addButton = document.createElement("button");
        addButton.type = "button";
        addButton.className = "secondary-button";
        addButton.style.marginTop = "10px";
        addButton.textContent = "Добавить в базу";

        addButton.addEventListener("click", () => {
            addNewDatabaseItem(report, config, addButton, message);
        });

        row.append(addButton, message);
    } else if (["not_checked", "not_applicable"].includes(status)) {
        const note = document.createElement("small");
        note.textContent = parsedValue ? "Проверка не выполнена." : "Значение в отчёте не указано — проверка не требуется.";
        row.append(note);
    }

    return row;
}


async function getReportAssignmentPoEntries(report) {
    const entries = [];
    if(report.review_options?.enabled && reviewApproved(report,'general_contractor')) return [{id:null,name:'Без ПО (согласовано)',role:'ПО'}];

    if (report.general_contractor && report.general_contractor_id) {
        entries.push({
            role: "ПО",
            source: "Генподрядчик",
            id: Number(report.general_contractor_id),
            name: report.resolved_general_contractor?.name || report.general_contractor,
        });
    }

    return entries;
}

function flattenAssignmentCategories(items) {
    const result = [];
    (items || []).forEach(parent => {
        result.push({
            id: parent.id,
            name: parent.name,
            label: parent.name,
        });
        (parent.children || []).forEach(child => {
            result.push({
                id: child.id,
                name: child.name,
                label: `${parent.name} → ${child.name}`,
            });
        });
    });
    return result;
}

async function renderReportAssignment(report, container) {
    if(report.review_options?.enabled) return renderReviewCategory(report,container);
    report.assignments_verified = false;
    updateExportButtons();
    // Keep the resolved assignment together with the report, keyed by PO.
    const assignmentKey = `${report.employee_id}:${report.entity_id ? `entity:${report.entity_id}` : report.object_id}:${report.general_contractor_id}`;
    if (report.assignment_key !== assignmentKey) {
        report.assignment_key = assignmentKey;
        report.assignments = {};
    }
    report.assignments ||= {};
    const section = document.createElement("div");
    section.style.marginTop = "18px";
    section.style.paddingTop = "14px";
    section.style.borderTop = "1px solid rgba(148, 163, 184, .35)";

    const title = document.createElement("h4");
    title.textContent = "Категория и назначение";
    section.append(title);
    container.append(section);

    if (getFinalReportStatus(report) !== "verified") {
        const note = document.createElement("small");
        note.textContent = "Сначала завершите проверку Инженера, Объекта и ПО.";
        section.append(note);
        return;
    }

    if (!report.employee_id || !(report.entity_id || report.object_id)) {
        const note = document.createElement("small");
        note.textContent = "Не удалось определить Инженера или Объект.";
        section.append(note);
        return;
    }

    const poEntries = await getReportAssignmentPoEntries(report);
    if (!section.isConnected) return;
    if (!poEntries.length) {
        const note = document.createElement("small");
        note.textContent = "ПО для назначения не определено.";
        section.append(note);
        return;
    }

    const loading = document.createElement("small");
    loading.textContent = "Проверяем назначение...";
    section.append(loading);

    try {
        const response = await fetch(`/api/employees/${report.employee_id}/assignments`);
        const data = await response.json();
        if (!section.isConnected) return;
        if (!response.ok) {
            throw new Error(data.message || data.detail || `HTTP ${response.status}`);
        }
        loading.remove();

        const assignments = Array.isArray(data.items) ? data.items : [];
        const objectId = Number(report.object_id);

        for (const po of poEntries) {
            const block = document.createElement("div");
            block.style.marginTop = "12px";
            block.style.padding = "12px";
            block.style.border = "1px solid rgba(148, 163, 184, .35)";
            block.style.borderRadius = "8px";

            const summary = document.createElement("div");
            summary.style.display = "grid";
            summary.style.gap = "4px";

            [
                ["Инженер", report.resolved_employee?.name || report.full_name],
                ["Объект", report.resolved_object?.name || report.object_name],
                ["ПО", po.name],
            ].forEach(([label, value]) => {
                const line = document.createElement("div");
                const strong = document.createElement("strong");
                strong.textContent = `${label}: `;
                line.append(strong, document.createTextNode(value || "—"));
                summary.append(line);
            });
            block.append(summary);

            const matches = assignments.filter(item =>
                (report.entity_id ? Number(item.entity_id) === Number(report.entity_id) : Number(item.object_id) === objectId) &&
                Number(item.po_id) === Number(po.id)
            );

            if (matches.length === 1) {
                report.assignments[po.id] = matches[0];
                const ok = document.createElement("div");
                ok.style.marginTop = "10px";
                const strong = document.createElement("strong");
                strong.textContent = "✓ Назначение найдено";
                ok.append(strong);

                const category = document.createElement("div");
                category.style.marginTop = "6px";
                category.textContent = `Категория: ${matches[0].category_name || "—"}`;
                ok.append(category);
                block.append(ok);
            } else if (matches.length > 1) {
                const warning = document.createElement("div");
                warning.style.marginTop = "10px";
                const strong = document.createElement("strong");
                strong.textContent = "⚠ Найдено несколько назначений";
                warning.append(strong);

                const select = document.createElement("select");
                select.setAttribute("aria-label", "Категория найденного назначения");
                select.add(new Option("Выберите категорию назначения", ""));
                matches.forEach(item => select.add(new Option(item.category_name || "—", item.id)));
                const previous = report.assignments[po.id];
                if (previous && matches.some(item => item.id === previous.id)) {
                    select.value = String(previous.id);
                } else {
                    delete report.assignments[po.id];
                }
                const confirm = document.createElement("button");
                confirm.type = "button";
                confirm.className = "secondary-button";
                confirm.textContent = "Выбрать назначение";
                const message = document.createElement("div");
                select.addEventListener("change", () => {
                    delete report.assignments[po.id];
                    message.textContent = "";
                    updateExportButtons();
                });
                confirm.addEventListener("click", () => {
                    const selected = matches.find(item => String(item.id) === select.value);
                    if (!selected) {
                        message.textContent = "Выберите категорию назначения.";
                        return;
                    }
                    report.assignments[po.id] = selected;
                    updateExportButtons();
                    message.textContent = `✓ Выбрана категория: ${selected.category_name}`;
                });
                warning.append(select, confirm, message);
                block.append(warning);
            } else {
                delete report.assignments[po.id];
                const warning = document.createElement("div");
                warning.style.marginTop = "10px";
                const strong = document.createElement("strong");
                strong.textContent = "⚠ Назначение не найдено";
                warning.append(strong);
                block.append(warning);

                const editor = document.createElement("div");
                editor.style.marginTop = "10px";

                const label = document.createElement("label");
                label.style.display = "block";
                label.style.marginBottom = "6px";
                label.textContent = "Категория";

                const select = document.createElement("select");
                select.setAttribute("aria-label", "Категория нового назначения");
                select.style.width = "100%";
                select.innerHTML = '<option value="">Выберите категорию</option>';

                const categoryResponse = await fetch("/api/object-categories");
                const categoryData = await categoryResponse.json();
                if (!categoryResponse.ok) {
                    throw new Error(categoryData.message || "Не удалось загрузить категории");
                }

                flattenAssignmentCategories(categoryData.items || []).forEach(item => {
                    select.add(new Option(item.label, item.id));
                });

                const message = document.createElement("small");
                message.style.display = "block";
                message.style.marginTop = "6px";

                const save = document.createElement("button");
                save.type = "button";
                save.className = "secondary-button";
                save.style.marginTop = "10px";
                save.textContent = "Сохранить назначение";

                save.addEventListener("click", async () => {
                    const categoryId = Number(select.value);
                    if (!categoryId) {
                        message.textContent = "Выберите категорию.";
                        return;
                    }

                    const oldText = save.textContent;
                    save.disabled = true;
                    select.disabled = true;
                    save.textContent = "Сохранение...";
                    message.textContent = "";

                    try {
                        const result = await apiPost(`/api/employees/${report.employee_id}/assignments`, {
                            ...(report.entity_id ? {entity_id: Number(report.entity_id)} : {object_id: Number(report.object_id)}),
                            po_id: Number(po.id),
                            category_id: categoryId,
                        });
                        report.assignments[po.id] = {
                            id: result.item.id,
                            employee_id: Number(report.employee_id),
                            entity_id: report.entity_id ?? null,
                            object_id: Number(report.object_id),
                            po_id: Number(po.id),
                            category_id: categoryId,
                            category_name: select.selectedOptions[0].textContent,
                        };
                        if (section.isConnected && detailsPanel.classList.contains("open")) {
                            openDetails(report);
                        }
                        updateExportButtons();
                        if (typeof loadEmployees === "function" && typeof employeeItems !== "undefined" && employeeItems.length) {
                            loadEmployees().catch(() => {});
                        }
                    } catch (error) {
                        message.textContent = `Ошибка: ${error.message}`;
                        save.disabled = false;
                        select.disabled = false;
                        save.textContent = oldText;
                    }
                });

                editor.append(label, select, save, message);
                block.append(editor);
            }

            section.append(block);
        }
        report.assignments_verified = true;
    } catch (error) {
        loading.textContent = `Не удалось проверить назначение: ${error.message}`;
        section.append(loading);
    } finally {
        updateExportButtons();
    }
}


function openDetails(report) {
    activeReportIndex = window.processingReports.indexOf(report);
    const footer = detailsPanel.querySelector('.details-footer');
    if (footer) {
        footer.querySelectorAll('[data-review-direction]').forEach(button => button.remove());
        for (const [direction, label] of [[-1, 'Назад'], [1, 'Далее']]) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'secondary-button';
            button.dataset.reviewDirection = direction;
            button.textContent = label;
            const reports = window.processingReports;
            let next = activeReportIndex + direction;
            while (next >= 0 && next < reports.length &&
                (reports[next].control_saved || (getFinalReportStatus(reports[next]) === 'verified' && reports[next].assignments_verified && reports[next].assignments?.[reports[next].general_contractor_id]?.category_id))) next += direction;
            button.disabled = Boolean(window.matrixActiveReport) || next < 0 || next >= reports.length || Boolean(report.control_saving);
            button.addEventListener('click', () => openDetails(reports[next]));
            footer.prepend(button);
        }
    }
    clearTimeout(closeDetailsTimer);
    setDetailsValue("detailsFile", report.filename);
    setDetailsValue("detailsEmployee", report.resolved_employee?.name || report.full_name);
    setDetailsValue("detailsPosition", report.position);
    setDetailsValue("detailsDate", report.report_date);
    setDetailsValue("detailsObject", [report.resolved_object?.name || report.object_name, report.resolved_subobject?.name].filter(Boolean).join(' → '));
    setDetailsValue("detailsGeneralContractor", report.resolved_general_contractor?.name || report.general_contractor);
    setDetailsValue("detailsSubcontractor", report.resolved_subcontractor?.name || report.subcontractor);

    document.getElementById("detailsTitle").textContent = "Результат проверки";

    const databaseStatus = document.getElementById("databaseStatus");
    databaseStatus.className = "database-status";
    databaseStatus.replaceChildren();
    if(report.review_options?.enabled){paintReportReviewSummary(report,databaseStatus);renderReviewRules(databaseStatus);}
    const dateRow = document.createElement("div");
    dateRow.textContent = `Дата: ${report.report_date || "—"}`;
    databaseStatus.append(dateRow);

    databaseStatus.append(
        buildCheckRow(report, {label:"Инженер",kind:"employee",statusField:"employee_status",parsedField:"full_name",candidatesField:"employee_candidates",resolvedField:"resolved_employee",idField:"employee_id",problemWords:["сотрудник","фио","инженер"]}),
        buildCheckRow(report, {label:"Объект / Подобъект",kind:"object",statusField:"object_status",parsedField:"object_name",candidatesField:"object_candidates",resolvedField:"resolved_object",idField:"object_id",problemWords:["объект"]}),
        buildCheckRow(report, {label:"ПО",kind:"po",statusField:"general_contractor_status",parsedField:"general_contractor",candidatesField:"general_contractor_candidates",resolvedField:"resolved_general_contractor",idField:"general_contractor_id",problemWords:["генподряд"]}),
        buildCheckRow(report, {label:"Субподрядчик",kind:"subcontractor",statusField:"subcontractor_status",parsedField:"subcontractor",candidatesField:"subcontractor_candidates",resolvedField:"resolved_subcontractor",idField:"subcontractor_id",problemWords:["субподряд"]})
    );

    renderReportAssignment(report, databaseStatus).catch(() => {
        report.assignments_verified = false;
    }).finally(() => {
        reportSaver.sync();
    });

    // Согласование действует только для текущего результата обработки.
    // Исходные значения парсера из Word не изменяются.
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
let selectedObjectId = null;

let objectSubobjects = [];
const expandedObjects = new Set();
const testObjectWorkspace = document.getElementById("objectsPage")?.dataset.identityPreviewEnabled === "true";
let objectView = "all";
const constructionIdentityPreview = testObjectWorkspace
    ? createConstructionIdentityPreview({
        getKnownEntities: () => [...objectItems, ...objectSubobjects],
        enablePromote: true,
        enableStandalone: true,
        onSaved: async item => {
            await loadObjects();
            const parent = objectItems.find(value => Number(value.entity_id ?? value.current_hierarchy?.entity_id) === Number(item.parent_entity_id));
            if (parent) expandedObjects.add(parent.id ?? `entity:${parent.entity_id}`);
            objectView = 'all';
            for (const tab of document.querySelectorAll('[data-object-view]')) {
                const selected = tab.dataset.objectView === 'all';
                tab.classList.toggle('active', selected);
                tab.setAttribute('aria-selected', String(selected));
            }
            const status = document.getElementById('objectStatusFilter');
            if (status) status.value = 'all';
            renderObjectList();
        },
    })
    : null;
const subobjectDirectoryEditor = createSubobjectDirectoryEditor({
    getObjects: () => objectItems,
    onSaved: async (child, oldParent) => {
        expandedObjects.add(oldParent);
        expandedObjects.add(child.object_id);
        await loadObjects();
    },
});

async function loadObjects() {
    const responses = await Promise.all([fetch("/api/objects"), fetch("/api/subobjects?include_inactive=true")]);
    const results = await Promise.all(responses.map(response => response.json()));
    if (responses.some(response => !response.ok)) throw new Error("Не удалось загрузить объекты и подобъекты");
    objectItems = results[0].items || results[0].objects || [];
    objectSubobjects = results[1].items || [];
    if (testObjectWorkspace && expandedObjects.size === 0) {
        const rootsWithChildren = objectCatalogRows(objectItems, objectSubobjects, {view: "all"});
        const firstExpanded = rootsWithChildren.find(row => row.children.length);
        if (firstExpanded) expandedObjects.add(firstExpanded.item.id);
    }
    renderObjectList();
}

function renderObjectList() {
    if (!objectList) return;
    const activity = testObjectWorkspace
        ? document.getElementById("objectStatusFilter").value
        : document.getElementById("objectActivityFilter").value;
    const archive = testObjectWorkspace ? "all" : document.getElementById("objectArchiveFilter").value;
    const sort = document.getElementById("objectSort").value;
    const children=objectSubobjects.filter(s=>archive==="all"||(s.is_archived||s.parent_is_archived)===(archive==="archived"));
    const parents=objectItems.filter(o=>archive==="all"||o.is_archived===(archive==="archived")||(archive==="archived"&&children.some(s=>s.object_id===o.id)));
    if (testObjectWorkspace) {
        const rows = objectCatalogRows(objectItems, objectSubobjects, {
            view: objectView, activity, query: objectSearchInput?.value || "", sort,
        });
        const itemCount = rows.reduce((count, row) => count + 1 + row.children.length, 0);
        if (objectCount) objectCount.textContent = `Записей: ${itemCount}`;
        renderObjectHierarchy(objectList, rows, {
            expanded: expandedObjects, activity: "all", testMode: true, parents: objectItems,
            selectedId: selectedObjectId,
            onSelect: id => { selectedObjectId = id; renderObjectList(); },
            onAdd: item => subobjectDirectoryEditor.open(item),
            onEdit: child => subobjectDirectoryEditor.open(null, child),
            onPromote: item => constructionIdentityPreview.open("promote", item),
            onMakeStandalone: item => constructionIdentityPreview.open("standalone", item),
        });
        return;
    }
    const rows = objectHierarchyRows(parents, children, {
        query: objectSearchInput?.value || "",
        sort,
        presence: document.getElementById("objectChildrenFilter").value,
        activity,
    });
    if (objectCount) objectCount.textContent = `Показано: ${rows.length} из ${objectItems.length}`;
    renderObjectWorkspace(objectList, rows, {
        expanded: expandedObjects, activity,
        onAdd: item => subobjectDirectoryEditor.open(item),
        onEdit: child => subobjectDirectoryEditor.open(null, child),
        onPromote: constructionIdentityPreview ? item => constructionIdentityPreview.open("promote", item) : null,
        onMakeStandalone: constructionIdentityPreview ? item => constructionIdentityPreview.open("standalone", item) : null,
    });
}
for (const id of ["objectSort", "objectChildrenFilter", "objectActivityFilter", "objectArchiveFilter", "objectStatusFilter"]) {
    document.getElementById(id)?.addEventListener("change", renderObjectList);
}
for (const tab of document.querySelectorAll("[data-object-view]")) {
    tab.addEventListener("click", () => {
        objectView = tab.dataset.objectView;
        for (const item of document.querySelectorAll("[data-object-view]")) {
            const selected = item === tab;
            item.classList.toggle("active", selected);
            item.setAttribute("aria-selected", String(selected));
        }
        renderObjectList();
    });
}

function openObjectDirectoryModal(item = null) {
    objectEditId = item?.entity_id != null ? `entity:${item.entity_id}` : item?.id || null;
    objectDirectoryModalTitle.textContent = item ? "Редактирование объекта" : "Добавить объект";
    objectDirectoryModalSave.textContent = item ? "Сохранить" : "Добавить";
    objectDirectoryNameInput.value = item?.name || "";
    const codeInput = document.getElementById("objectDirectoryCodeInput");
    if (codeInput) codeInput.value = item?.code ?? item?.object_code ?? item?.code_value ?? item?.construction_code ?? "";
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
        const item = objectItems.find(value => (editButton.dataset.id.startsWith("entity:") ? `entity:${value.entity_id}` : String(value.id)) === editButton.dataset.id);
        if (item) openObjectDirectoryModal(item);
        return;
    }

    const archiveButton = event.target.closest(".archive-object-directory");
    const archiveChildButton = event.target.closest(".archive-subobject-directory");
    if (archiveButton || archiveChildButton) {
        const isChild = Boolean(archiveChildButton);
        const button = archiveButton || archiveChildButton;
        const item = (isChild ? objectSubobjects : objectItems)
            .find(value => (button.dataset.id.startsWith("entity:") ? `entity:${value.entity_id}` : String(value.id)) === button.dataset.id);
        if (!item) return;
        const archived = Boolean(item.is_archived);
        const action = archived ? "restore" : "archive";
        if (!archived && !confirm(`Переместить «${item.name}» в архив? История и связи сохранятся.`)) return;
        try {
            const kind = isChild ? "subobjects" : "objects";
            const response = await fetch(item.entity_id != null ? `/api/${kind}/${item.entity_id}/${action}?id_type=entity` : `/api/${kind}/${item.id}/${action}`, {method: "POST"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || "Не удалось изменить архивный статус");
            await loadObjects();
            if (typeof employeeItems !== "undefined" && employeeItems.length) await loadEmployees();
        } catch (error) {
            alert(error.message);
        }
        return;
    }

    const deleteButton = event.target.closest(".delete-object-directory");
    if (!deleteButton) return;
    const item = objectItems.find(value => String(value.id) === deleteButton.dataset.id);
    if (!item) return;
    if (!confirm(`Переместить объект «${item.name}» в архив? История и связи сохранятся.`)) return;

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
            objectEditId ? (String(objectEditId).startsWith("entity:") ? `/api/objects/${String(objectEditId).slice(7)}?id_type=entity` : `/api/objects/${objectEditId}`) : "/api/objects",
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
    showMainSection(objectsPage, objectsNavButton);
    activateObjectTab(objectsTab);
    try { await loadObjects(); }
    catch (error) { objectList.innerHTML = `<div class="category-empty">${error.message}</div>`; }
});

backToProcessingButton?.addEventListener("click", () => {
    showMainSection(processingPage, document.getElementById("processingNavButton"));
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
        const categoryNote=document.createElement('small');categoryNote.style.display='block';
        categoryNote.textContent='Категория по умолчанию: '+(item.default_category_name||'не задана');
        row.querySelector('.category-name').append(categoryNote);
        row.querySelector(".edit-po").dataset.id = item.id;
        row.querySelector(".delete-po").dataset.id = item.id;
        poList.append(row);
    });
}


async function openPoModal(item = null) {
    poEditId = item?.id || null;
    poModalTitle.textContent = item ? "Переименовать ПО" : "Добавить ПО";
    poModalSave.textContent = item ? "Сохранить" : "Добавить";
    poNameInput.value = item?.name || "";
    poModalError.hidden = true;
    poModalError.textContent = "";
    poModal.hidden = false;
    const category=document.getElementById('poDefaultCategory');
    category.replaceChildren(new Option('Не задана',''));category.disabled=true;poModalSave.disabled=true;
    try{
        const response=await fetch('/api/object-categories');const data=await response.json();
        if(!response.ok)throw Error(data.message||'Не удалось загрузить категории');
        for(const c of flattenAssignmentCategories(data.items))category.add(new Option(c.label,c.id));
        category.value=item?.default_category_id?String(item.default_category_id):'';
        category.disabled=false;poModalSave.disabled=false;
    }catch(error){poModalError.textContent=error.message;poModalError.hidden=false;}

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
        const item = poItems.find(value => (editButton.dataset.id.startsWith("entity:") ? `entity:${value.entity_id}` : String(value.id)) === editButton.dataset.id);
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
            body: JSON.stringify({name,default_category_id:document.getElementById('poDefaultCategory').value?Number(document.getElementById('poDefaultCategory').value):null}),
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
const positionEquipmentInput=document.getElementById("positionEquipmentInput");
const positionPlannedCountInput=document.getElementById("positionPlannedCountInput");
const employeesNavButton=document.getElementById("employeesNavButton"),employeesPage=document.getElementById("employeesPage"),backFromEmployeesButton=document.getElementById("backFromEmployeesButton"),employeesTab=document.getElementById("employeesTab"),positionsTab=document.getElementById("positionsTab"),employeesPanel=document.getElementById("employeesPanel"),positionsPanel=document.getElementById("positionsPanel"),positionList=document.getElementById("positionList"),addPositionButton=document.getElementById("addPositionButton"),positionModal=document.getElementById("positionModal"),positionModalTitle=document.getElementById("positionModalTitle"),positionModalClose=document.getElementById("positionModalClose"),positionModalCancel=document.getElementById("positionModalCancel"),positionModalSave=document.getElementById("positionModalSave"),positionNameInput=document.getElementById("positionNameInput"),positionDescriptionInput=document.getElementById("positionDescriptionInput"),positionReportDescriptionInput=document.getElementById("positionReportDescriptionInput"),positionRequiresDailyReportInput=document.getElementById("positionRequiresDailyReportInput"),positionAosDescriptionInput=document.getElementById("positionAosDescriptionInput"),positionModalError=document.getElementById("positionModalError");
let positionItems=[],positionEditId=null;
document.getElementById("positionWorkLocation").addEventListener("change",()=>syncPositionSchedule());
function showMainSection(section, nav) {
    closeDetails();
    ["processingPage", "objectsPage", "employeesPage", "crewsPage", "contractorsPage", "logsPage", "journalPage", "railTicketsPage", "luvrCalendarPage", "luvrMonthPage", "productionMatrixPage", "deploymentPage", "settingsPage", "vouPage"].forEach(id => {
        const page = document.getElementById(id);
        if (page) page.hidden = page !== section;
    });
    const luvrTabs={productionMatrixPage:'productionMatrixNavButton',railTicketsPage:'railTicketsNavButton',luvrMonthPage:'luvrMonthNavButton',luvrCalendarPage:'luvrCalendarNavButton'};
    const luvrTab=luvrTabs[section?.id];
    const luvrNavigation=document.getElementById('luvrNavigation');
    if(luvrNavigation){
        luvrNavigation.hidden=!luvrTab;
        if(luvrTab)luvrNavigation.dataset.activeTab=luvrTab;
        for(const id of Object.values(luvrTabs)){
            const button=document.getElementById(id);button.classList.toggle('active',id===luvrTab);
            if(id===luvrTab)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
        }
    }
    setActiveNav(luvrTab?document.getElementById('luvrNavButton'):nav);
}

document.getElementById('luvrNavButton')?.addEventListener('click',()=>{
    const tab=document.getElementById('luvrNavigation')?.dataset.activeTab||'luvrMonthNavButton';
    document.getElementById(tab).click();
});
document.getElementById("processingNavButton")?.addEventListener("click", event => {
    showMainSection(processingPage, event.currentTarget);
});
document.getElementById("logsNavButton")?.addEventListener("click", event => {
    showMainSection(document.getElementById("logsPage"), event.currentTarget);
    renderProcessingLogs();
});
document.getElementById("refreshLogsButton")?.addEventListener("click", renderProcessingLogs);
document.getElementById("backFromLogsButton")?.addEventListener("click", () => {
    showMainSection(processingPage, document.getElementById("processingNavButton"));
});
function activateEmployeeTab(tab){[employeesTab,positionsTab].forEach(b=>b?.classList.remove("active"));tab?.classList.add("active");employeesPanel.hidden=tab!==employeesTab;positionsPanel.hidden=tab!==positionsTab}
async function loadPositions(){const r=await fetch("/api/positions"),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось загрузить должности");positionItems=x.items||[];renderPositionList()}
function renderPlannedCount(container,item){
    container.replaceChildren();
    const button=document.createElement('button');button.type='button';button.className='position-count-button';
    button.textContent=String(item.planned_count??0);button.title='Изменить плановое количество';
    button.setAttribute('aria-label',`Плановое количество: ${button.textContent}. Изменить`);
    button.onclick=()=>{
        const input=document.createElement('input');input.type='number';input.min='0';input.max='2147483647';input.step='1';input.required=true;input.value=item.planned_count??0;input.setAttribute('aria-label','Плановое количество');
        const save=document.createElement('button');save.type='button';save.textContent='✓';save.title='Сохранить';save.setAttribute('aria-label','Сохранить плановое количество');
        const cancel=document.createElement('button');cancel.type='button';cancel.textContent='×';cancel.title='Отмена';cancel.setAttribute('aria-label','Отменить изменение');
        const error=document.createElement('small');error.setAttribute('role','alert');error.hidden=true;
        let busy=false;
        cancel.onclick=()=>{if(!busy)renderPlannedCount(container,item);};
        save.onclick=async()=>{
            if(busy||!input.reportValidity())return;
            const count=Number(input.value);if(count===item.planned_count){renderPlannedCount(container,item);return;}
            busy=true;input.disabled=save.disabled=cancel.disabled=true;error.hidden=true;
            try{
                const r=await fetch(`/api/positions/${item.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({name:item.name,action_description:item.action_description,planned_count:count})});
                const result=await r.json();if(!r.ok)throw new Error(result.message||'Не удалось сохранить количество');
                Object.assign(item,result.item);renderPlannedCount(container,item);
            }catch(e){error.textContent=e.message;error.hidden=false;}
            finally{busy=false;input.disabled=save.disabled=cancel.disabled=false;}
        };
        input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();save.click();}if(e.key==='Escape'){e.preventDefault();cancel.click();}};
        container.replaceChildren(input,save,cancel,error);input.focus();input.select();
    };
    container.append(button);
}
function renderPositionList(){positionList.replaceChildren();if(!positionItems.length){positionList.innerHTML='<div class="category-empty">Должности не найдены</div>';return}const header=document.createElement("div");header.className="position-table-header";header.innerHTML="<strong>Должность</strong><strong>Заполнение описаний</strong><strong>Действия</strong>";const plannedHeader=document.createElement("strong");plannedHeader.textContent="Плановое количество";header.insertBefore(plannedHeader,header.lastElementChild);positionList.append(header);positionItems.forEach(item=>{const row=document.createElement("div");row.className="position-table-row";row.innerHTML='<div class="position-title"></div><div class="position-description position-description-status"></div><div class="category-actions"><button type="button" class="category-icon-button edit-position" title="Редактировать">✎</button><button type="button" class="category-icon-button danger delete-position" title="Удалить">🗑</button></div>';row.querySelector(".position-title").textContent=item.name;const labels=positionWorkLabels(item);const settings=document.createElement("small");settings.className="position-work-settings";settings.textContent=`${labels.specialty} · ${labels.location} · ${labels.schedule}`;row.querySelector(".position-title").append(settings);const d=row.querySelector(".position-description");for(const [label,value] of [["Действия",item.action_description],["Отчёт",item.report_description],["АОС",item.aos_description]]){const badge=document.createElement("span");badge.className=`position-fill-badge ${value?"filled":"empty"}`;badge.textContent=`${label}: ${value?"✓":"—"}`;d.append(badge)}const planned=document.createElement("div");planned.className="position-planned-count";renderPlannedCount(planned,item);row.insertBefore(planned,row.querySelector(".category-actions"));row.querySelector(".edit-position").dataset.id=item.id;row.querySelector(".delete-position").dataset.id=item.id;positionList.append(row)})}
function openPositionModal(item=null){positionEditId=item?.id||null;positionModalTitle.textContent=item?"Редактировать должность":"Добавить должность";positionModalSave.textContent=item?"Сохранить":"Добавить";positionNameInput.value=item?.name||"";positionDescriptionInput.value=item?.action_description||"";positionReportDescriptionInput.value=item?.report_description||"";positionEquipmentInput.value=item?.equipment_description||"";positionAosDescriptionInput.value=item?.aos_description||"";positionRequiresDailyReportInput.value=item?.requires_daily_report?"true":"false";positionPlannedCountInput.value=item?.planned_count??0;fillPositionSettings(item);positionModalError.hidden=true;positionModal.hidden=false;setTimeout(()=>positionNameInput.focus(),0)}
function closePositionModal(){positionModal.hidden=true}
employeesNavButton?.addEventListener("click",()=>{closeDetails();showMainSection(employeesPage,employeesNavButton);activateEmployeeTab(employeesTab)});
backFromEmployeesButton?.addEventListener("click",()=>showMainSection(processingPage,document.querySelector(".nav-item:first-child")));
employeesTab?.addEventListener("click",()=>activateEmployeeTab(employeesTab));
positionsTab?.addEventListener("click",async()=>{activateEmployeeTab(positionsTab);try{await loadPositions()}catch(e){positionList.innerHTML=`<div class="category-empty">${e.message}</div>`}});
addPositionButton?.addEventListener("click",()=>openPositionModal());
positionModalClose?.addEventListener("click",closePositionModal);positionModalCancel?.addEventListener("click",closePositionModal);positionModal?.addEventListener("click",e=>{if(e.target===positionModal)closePositionModal()});
positionList?.addEventListener("click",async e=>{const eb=e.target.closest(".edit-position");if(eb){const item=positionItems.find(x=>String(x.id)===eb.dataset.id);if(item)openPositionModal(item);return}const db=e.target.closest(".delete-position");if(!db)return;const item=positionItems.find(x=>String(x.id)===db.dataset.id);if(!item||!confirm(`Удалить должность «${item.name}»?`))return;try{const r=await fetch(`/api/positions/${item.id}`,{method:"DELETE"}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить должность");await loadPositions()}catch(err){alert(err.message)}});
positionModalSave?.addEventListener("click",async()=>{const name=positionNameInput.value.trim();if(!positionPlannedCountInput.reportValidity())return;if(!name){positionModalError.textContent="Введите название должности";positionModalError.hidden=false;return}positionModalSave.disabled=true;positionModalError.hidden=true;try{const url=positionEditId?`/api/positions/${positionEditId}`:"/api/positions",r=await fetch(url,{method:positionEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,action_description:positionDescriptionInput.value.trim()||null,report_description:positionReportDescriptionInput.value.trim()||null,aos_description:positionAosDescriptionInput.value.trim()||null,equipment_description:positionEquipmentInput.value,planned_count:Number(positionPlannedCountInput.value),requires_daily_report:positionRequiresDailyReportInput.value==="true",...positionSettingsPayload()})}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить должность");closePositionModal();await loadPositions()}catch(err){positionModalError.textContent=err.message;positionModalError.hidden=false}finally{positionModalSave.disabled=false}});


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
const employeeArchiveFilter=document.getElementById("employeeArchiveFilter");
let employeeListRequest=0;

async function loadEmployees(){
    const version=++employeeListRequest;
    const response=await fetch(employeeArchiveFilter?.value==="all"?"/api/employees?include_archived=true":employeeArchiveListUrl(employeeArchiveFilter?.value==="archived"));
    const result=await response.json();
    if(version!==employeeListRequest)return;
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
    if(typeof renderEmployeeWorkspace==='function')renderEmployeeWorkspace(employeeItems);
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
    showEmployeePositionSettings(item);
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
let assignmentObjectChoices = [];
async function loadAssignmentDictionaries(){const [a,b,c]=await Promise.all([fetch("/api/objects?archive=active"),fetch("/api/po-types"),fetch("/api/object-categories")]);const [ax,bx,cx]=await Promise.all([a.json(),b.json(),c.json()]);if(!a.ok)throw new Error(ax.message||"Не удалось загрузить объекты");if(!b.ok)throw new Error(bx.message||"Не удалось загрузить ПО");if(!c.ok)throw new Error(cx.message||"Не удалось загрузить категории");assignmentObjectChoices=await ConstructionChoices.load(async url=>{const r=await fetch(url);if(!r.ok)throw new Error(String(r.status));return r.json();},ax.items||ax.objects||[]);ConstructionChoices.fill(assignmentObjectSelect,assignmentObjectChoices);assignmentPoSelect.innerHTML='<option value="">Выберите ПО</option>';(bx.items||[]).forEach(x=>assignmentPoSelect.add(new Option(x.name,x.id)));assignmentCategorySelect.innerHTML='<option value="">Выберите категорию</option>';(cx.items||[]).forEach(x=>assignmentCategorySelect.add(new Option(x.name,x.id)))}
async function openAssignmentEditor(item=null){try{await loadAssignmentDictionaries();ConstructionChoices.fill(assignmentObjectSelect,assignmentObjectChoices,item);assignmentEditId=item?.id||null;assignmentPoSelect.value=item?String(item.po_id):"";assignmentCategorySelect.value=item?String(item.category_id):"";assignmentSaveButton.textContent=item?"Сохранить":"Добавить";assignmentError.hidden=true;assignmentEditor.hidden=false}catch(e){alert(e.message)}}
function closeAssignmentEditor(){assignmentEditor.hidden=true;assignmentEditId=null}

let employeeModalContext=null;
async function openEmployeeModal(item=null,context=null){
    employeeModalContext=context;
    document.getElementById('employeeTicketMatches')?.remove();
    employeeEditId=item?.id||null;
    employeeModalTitle.textContent=item?"Карточка сотрудника":"Добавить сотрудника";
    employeeModalSave.textContent=item?"Сохранить":"Добавить";
    employeeModalError.hidden=true;employeeModalError.textContent="";
    try{
        await loadPositions();
        if(!crewItems.length)await loadCrews();
        fillEmployeeSelects();
        employeeNameInput.value=item?.full_name||context?.full_name||"";
        employeePositionSelect.value=item?.position_id==null?"":String(item.position_id);
        employeePhoneInput.value=item?.phone||"";
        document.getElementById("employeeEmailInput").value=item?.email||"";
        fillEmployeePersonalSettings(item);
        document.getElementById("employeeDismissalDate").value=item?.dismissal_date||"";
        openEmployeeLuvrHistory(item?.id||null);
        employeeCrewSelect.value=item?.crew_id==null?"":String(item.crew_id);
        updateEmployeeDescription();updateEmployeeCrewPreview();closeAssignmentEditor();
        if(item){employeeAssignmentsSection.hidden=false;await loadEmployeeAssignments(item.id)}else{employeeAssignmentsSection.hidden=true;employeeAssignments=[]}
        employeeModal.hidden=false;setTimeout(()=>employeeNameInput.focus(),0);
    }catch(error){alert(error.message)}
}
function closeEmployeeModal(){employeeModal.hidden=true;employeeModalContext=null}
employeeSearchInput?.addEventListener("input",renderEmployees);
employeeArchiveFilter?.addEventListener("change",()=>loadEmployees().catch(error=>alert(error.message)));
employeePositionSelect?.addEventListener("change",updateEmployeeDescription);
employeeCrewSelect?.addEventListener("change",updateEmployeeCrewPreview);
addEmployeeButton?.addEventListener("click",()=>openEmployeeModal());
employeeModalClose?.addEventListener("click",closeEmployeeModal);
employeeModalCancel?.addEventListener("click",closeEmployeeModal);
employeeModal?.addEventListener("click",e=>{if(e.target===employeeModal)closeEmployeeModal()});
employeeList?.addEventListener("click",async e=>{
    const edit=e.target.closest(".edit-employee");
    if(edit){const item=employeeItems.find(x=>x.id===Number(edit.dataset.id));if(item)await openEmployeeModal(item);return}
    const archive=e.target.closest(".employee-archive-button");
    if(archive){
        const item=employeeItems.find(x=>x.id===Number(archive.dataset.id));
        if(!item||archive.disabled)return;
        archive.disabled=true;
        try{const changed=await changeEmployeeArchive(item,async(url,options)=>{const r=await fetch(url,options),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось изменить архивное состояние");return x;},message=>confirm(message));if(changed)await loadEmployees()}catch(error){alert(error.message)}
        finally{archive.disabled=false}
    }
});
addAssignmentButton?.addEventListener("click",()=>openAssignmentEditor());
assignmentCancelButton?.addEventListener("click",closeAssignmentEditor);
employeeAssignmentsList?.addEventListener("click",async e=>{const edit=e.target.closest(".edit-assignment"),del=e.target.closest(".delete-assignment");if(edit){const item=employeeAssignments.find(x=>x.id===Number(edit.dataset.id));if(item)await openAssignmentEditor(item);return}if(del){const item=employeeAssignments.find(x=>x.id===Number(del.dataset.id));if(!item||!confirm(`Удалить назначение на объект «${item.object_name}»?`))return;try{const r=await fetch(`/api/employees/${employeeEditId}/assignments/${item.id}`,{method:"DELETE"}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось удалить назначение");await loadEmployeeAssignments(employeeEditId)}catch(err){alert(err.message)}}});
assignmentSaveButton?.addEventListener("click",async()=>{if(!employeeEditId)return;const objectReference=ConstructionChoices.reference(assignmentObjectSelect.value),po_id=Number(assignmentPoSelect.value),category_id=Number(assignmentCategorySelect.value);if(!assignmentObjectSelect.value||!po_id||!category_id){assignmentError.textContent="Выберите объект, ПО и категорию";assignmentError.hidden=false;return}assignmentSaveButton.disabled=true;assignmentError.hidden=true;try{const url=assignmentEditId?`/api/employees/${employeeEditId}/assignments/${assignmentEditId}`:`/api/employees/${employeeEditId}/assignments`;const r=await fetch(url,{method:assignmentEditId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...objectReference,po_id,category_id})}),x=await r.json();if(!r.ok)throw new Error(x.message||"Не удалось сохранить назначение");closeAssignmentEditor();await loadEmployeeAssignments(employeeEditId)}catch(err){assignmentError.textContent=err.message;assignmentError.hidden=false}finally{assignmentSaveButton.disabled=false}});

employeeModalSave?.addEventListener("click",async()=>{
    if(!document.getElementById("employeeEmailInput").reportValidity())return;
    const full_name=employeeNameInput.value.trim();
    if(!full_name){employeeModalError.textContent="Введите ФИО сотрудника";employeeModalError.hidden=false;return}
    employeeModalSave.disabled=true;employeeModalError.hidden=true;
    try{
        const body={
            full_name,
            ...employeePersonalSettingsPayload(),
            dismissal_date:document.getElementById("employeeDismissalDate").value||null,
            position_id:employeePositionSelect.value?Number(employeePositionSelect.value):null,
            phone:employeePhoneInput.value.trim()||null,
            email:document.getElementById("employeeEmailInput").value.trim()||null,
            crew_id:employeeCrewSelect.value?Number(employeeCrewSelect.value):null
        };
        const context=employeeModalContext;
        if(context?.beforeSave)await context.beforeSave(body);
        const x=await saveEmployeeData(employeeEditId,body);
        closeEmployeeModal();document.dispatchEvent(new CustomEvent("employee-saved",{detail:{id:x.id}}));
        if(context?.onSaved)await context.onSaved(x);
        await loadEmployees();
    }catch(error){employeeModalError.textContent=error.message;employeeModalError.hidden=false;if(employeeModalContext?.onError)await employeeModalContext.onError();}
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
    const q=(crewSearchInput?.value||"").trim().toLocaleLowerCase("ru");
    const items=crewItems.filter(item=>!q||[
        item.name,item.driver_full_name,item.driver_phone,item.vehicle_make,item.vehicle_plate
    ].some(v=>(v||"").toLocaleLowerCase("ru").includes(q)));
    if(crewCount)crewCount.textContent=`Показано: ${items.length} из ${crewItems.length}`;
    renderCrewWorkspace(crewList,items);
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
    showMainSection(crewsPage, crewsNavButton);
    try{await refreshCrews()}
    catch(error){crewList.innerHTML=`<div class="category-empty">${error.message}</div>`}
});
backFromCrewsButton?.addEventListener("click",()=>{
    showMainSection(processingPage, document.getElementById("processingNavButton"));
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
    document.getElementById("journalPage").hidden = true;
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
