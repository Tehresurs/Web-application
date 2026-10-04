/* Bind results to the folder used for this request, never the later input value. */
function attachReportSourcePaths(reports, folder) {
    const base = String(folder || "").trim().replace(/[\\/]+$/, "");
    if (!base) return reports;
    for (const report of reports) {
        if (!report.source_path && report.filename && !/[\\/]/.test(report.filename) &&
            report.filename !== "." && report.filename !== "..") {
            report.source_path = `${base}/${report.filename}`;
        }
    }
    return reports;
}

/* Manual report completion; readiness always comes from the server. */
class ReportSaveController {
    constructor({button, retryButton, message, fetchRequest, ready, onState}) {
        Object.assign(this, {button, retryButton, message, fetchRequest, ready, onState});
        this.report = null;
        this.version = 0;
        button.addEventListener("click", () => this.save());
        retryButton.addEventListener("click", () => this.refresh());
    }

    payload(report) {
        const payload = {path: report.source_path, assignments: {}};
        payload.subobject_id = report.subobject_id ?? null;
        if (Object.keys(report.alias_conflicts || {}).length) payload.unresolved_aliases = Object.keys(report.alias_conflicts);
        for (const key of ["employee", "object", "general_contractor", "subcontractor"]) {
            if (report[`${key}_status`] === "found" && report[`${key}_id`]) {
                payload[`${key}_id`] = report[`${key}_id`];
            }
        }
        for (const po of [payload.general_contractor_id].filter(Boolean)) {
            if (report.assignments?.[po]?.id) payload.assignments[po] = report.assignments[po].id;
        }
        return payload;
    }

    bind(report) {
        this.version++;
        this.checking = false;
        this.report = report;
        this.canSave = false;
        this.message.textContent = "Проверяем возможность сохранения...";
        this.paint();
    }

    close() {
        this.version++;
        this.checking = false;
        this.report = null;
        this.canSave = false;
        this.paint();
    }

    paint() {
        const report = this.report;
        this.button.disabled = Boolean(!report || !this.canSave || report.control_saved || report.control_saving);
        this.button.textContent = report?.control_saved ? "✓ Результат сохранён"
            : report?.control_saving ? "Сохранение..." : "Сохранить результат";
        this.retryButton.hidden = !report || report.control_saved || report.control_saving;
        this.retryButton.disabled = this.checking === true;
        this.onState(report);
    }

    async request(path, payload) {
        const response = await this.fetchRequest(path, {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            const detail = result.detail;
            throw new Error(detail?.problems?.join("; ") || result.message ||
                (typeof detail === "string" ? detail : detail?.message) || "Не удалось выполнить запрос");
        }
        return result;
    }

    async refresh() {
        const report = this.report;
        if (!report || report.control_saving) return;
        const version = ++this.version;
        this.canSave = false;
        this.checking = true;
        this.message.textContent = "Проверяем возможность сохранения...";
        this.paint();
        const payload = this.payload(report);
        const signature = JSON.stringify(payload);
        try {
            if (!payload.path) throw new Error("Повторите обработку папки, чтобы определить исходный файл.");
            const result = await this.request("/api/daily-control-results/check", payload);
            if (version !== this.version || report !== this.report || signature !== JSON.stringify(this.payload(report))) return;
            report.control_saved = result.saved === true;
            this.canSave = result.can_save === true && this.ready(report) && !report.control_saved;
            this.message.textContent = report.control_saved ? "Факт контроля уже записан в журнал."
                : this.canSave ? `Проверка завершена. Будет сохранена дата отчёта: ${report.report_date}.`
                    : (result.problems || []).join("; ") || "Устраните замечания и выберите назначения для всех ПО.";
        } catch (error) {
            if (version === this.version && report === this.report) this.message.textContent = error.message;
        } finally {
            if (version === this.version) {
                this.checking = false;
                this.paint();
            }
        }
    }

    async save() {
        const report = this.report;
        if (!report || !this.canSave || !this.ready(report) || report.control_saved || report.control_saving) return;
        ++this.version;
        this.checking = false;
        this.canSave = false;
        report.control_saving = true;
        const payload = this.payload(report);
        this.message.textContent = "Сохраняем результат...";
        this.paint();
        try {
            const result = await this.request("/api/daily-control-results", payload);
            if (result.saved !== true) throw new Error("Сервер не подтвердил сохранение. Повторите проверку.");
            report.control_saved = true;
            report.control_results = result.results;
            if (report === this.report) this.message.textContent = result.created === false ? "Этот результат уже сохранён." : "Факт контроля записан в журнал.";
        } catch (error) {
            if (report === this.report) this.message.textContent = `${error.message}. Нажмите «Проверить готовность» перед повторной попыткой.`;
        } finally {
            report.control_saving = false;
            if (report === this.report) this.paint();
        }
    }
}

class BatchReportSaveController extends ReportSaveController {
    constructor(options) {
        super(options);
        this.getReports = options.getReports;
        this.signature = null;
    }

    key() {
        return JSON.stringify(this.getReports().map(report => [this.payload(report), this.ready(report)]));
    }

    sync() {
        if (this.saving || this.signature === this.key()) return;
        this.signature = this.key();
        ++this.version;
        this.canSave = false;
        clearTimeout(this.timer);
        this.paint();
        this.timer = setTimeout(() => this.refresh(), 200);
    }

    paint() {
        const reports = this.getReports();
        const saved = reports.length > 0 && reports.every(report => report.control_saved);
        this.button.disabled = !this.canSave || this.checking === true || this.saving === true || saved;
        this.button.textContent = saved ? "✓ Результат сохранён" : this.saving ? "Сохранение..." : "Сохранить результат";
        this.retryButton.hidden = !reports.length || saved;
        this.retryButton.disabled = Boolean(this.checking || this.saving);
        this.onState(Boolean(this.saving));
    }

    async refresh() {
        if (this.saving) return;
        clearTimeout(this.timer);
        const version = ++this.version;
        const reports = [...this.getReports()];
        const signature = this.key();
        this.signature = signature;
        this.canSave = false;
        this.checking = true;
        this.message.textContent = reports.length ? "Проверяем готовность всех отчётов..." : "Сначала обработайте отчёты.";
        this.paint();
        const problems = [];
        try {
            for (const report of reports) {
                if (version !== this.version || signature !== this.key()) return;
                if (report.control_saved) continue;
                if (!report.source_path) {
                    problems.push(`${report.filename}: в результате обработки не указан путь к исходному файлу.`);
                    continue;
                }
                const result = await this.request("/api/daily-control-results/check", this.payload(report));
                if (version !== this.version || signature !== this.key()) return;
                report.control_saved = result.saved === true;
                if (!report.control_saved && (!result.can_save || !this.ready(report))) {
                    problems.push(`${report.filename}: ${(result.problems || []).join('; ') || 'завершите проверку и выбор назначений'}`);
                }
            }
            const saved = reports.length > 0 && reports.every(report => report.control_saved);
            this.canSave = reports.length > 0 && !saved && !problems.length;
            this.verifiedSignature = signature;
            this.message.textContent = saved ? "Все результаты записаны в журнал."
                : problems.length ? problems.join("\n")
                : reports.length ? `Готово к сохранению: ${reports.filter(report => !report.control_saved).length} отчётов. Даты — из исходных отчётов.`
                : "Сначала обработайте отчёты.";
        } catch (error) {
            if (version === this.version) this.message.textContent = `${error.message}. Повторите проверку готовности.`;
        } finally {
            if (version === this.version) {
                this.checking = false;
                this.paint();
            }
        }
    }

    async save() {
        if (this.saving || !this.canSave || this.verifiedSignature !== this.key()) return;
        const reports = [...this.getReports()];
        if (!reports.length || reports.some(report => !report.control_saved && !this.ready(report))) return;
        ++this.version;
        this.saving = true;
        this.canSave = false;
        this.paint();
        let current;
        let allDuplicates = true;
        try {
            for (const report of reports) {
                current = report;
                if (report.control_saved) continue;
                const result = await this.request("/api/daily-control-results", this.payload(report));
                if (result.saved !== true) throw new Error("Сервер не подтвердил сохранение");
                report.control_saved = true;
                report.control_results = result.results;
                if (result.created !== false) allDuplicates = false;
                this.message.textContent = `Сохранено отчётов: ${reports.filter(item => item.control_saved).length} из ${reports.length}.`;
            }
            this.message.textContent = allDuplicates ? "Этот результат уже сохранён." : "Все результаты записаны в журнал.";
        } catch (error) {
            this.message.textContent = `${current.filename}: ${error.message}. Сохранено ${reports.filter(item => item.control_saved).length} из ${reports.length}. Повторите проверку готовности; сохранённые отчёты повторно записаны не будут.`;
        } finally {
            this.saving = false;
            this.paint();
        }
    }
}

if (typeof module !== "undefined") module.exports = {ReportSaveController, BatchReportSaveController, attachReportSourcePaths};
