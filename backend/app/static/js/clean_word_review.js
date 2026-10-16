/* Separate clean-start Word review flow; no legacy processing endpoints. */
(function (root) {
    const BASE = '/api/clean-construction-entities';

    function createCleanWordReviewClient(request = fetch, makeFormData = () => new FormData()) {
        async function jsonRequest(path, method = 'GET', payload) {
            const response = await request(BASE + path, {
                method,
                headers: {'Content-Type': 'application/json'},
                body: payload === undefined ? undefined : JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(typeof result.detail === 'string'
                    ? result.detail
                    : result.message || 'Не удалось выполнить операцию');
            }
            return result;
        }
        return {
            async verify() {
                const {item} = await jsonRequest('/environment');
                if (item.profile !== 'test' || item.contract !== 'entity_id' || item.schema !== 'public') {
                    throw new Error('Тестовое clean-start окружение не подтверждено');
                }
            },
            async dictionaries() {
                const {dictionaries} = await jsonRequest('/word-report/dictionaries');
                return dictionaries;
            },
            async parse(file) {
                const form = makeFormData();
                form.append('file', file);
                const response = await request(BASE + '/word-report/parse', {
                    method: 'POST',
                    body: form,
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(typeof result.detail === 'string'
                        ? result.detail
                        : result.message || 'Не удалось разобрать Word-отчёт');
                }
                return result.intermediate_report;
            },
            confirm(payload) {
                return jsonRequest('/word-report/confirm', 'POST', payload);
            },
        };
    }

    function buildCleanWordConfirmation(report, selection, acknowledged) {
        if (!acknowledged) throw new Error('Подтвердите, что обязательные поля проверены');
        const reportDate = selection.reportDate;
        if (!/^\d{4}-\d{2}-\d{2}$/.test(reportDate || '') ||
            Number.isNaN(Date.parse(reportDate)) ||
            new Date(`${reportDate}T00:00:00Z`).toISOString().slice(0, 10) !== reportDate) {
            throw new Error('Укажите корректную дату отчёта');
        }
        const employeeId = Number(selection.employeeId);
        const entityId = Number(selection.entityId);
        const generalId = Number(selection.generalContractorId);
        if (![employeeId, entityId, generalId].every(value => Number.isSafeInteger(value) && value > 0)) {
            throw new Error('Выберите сотрудника, объект и генподрядчика');
        }
        const business = report.business_data;
        const subcontractorRequired =
            business.subcontractor_match.status !== 'not_applicable';
        const subcontractorId = selection.subcontractorId
            ? Number(selection.subcontractorId)
            : null;
        if (subcontractorRequired &&
            (!Number.isSafeInteger(subcontractorId) || subcontractorId <= 0)) {
            throw new Error('Выберите субподрядчика или отметьте его как отсутствующего');
        }
        return {
            confirmed: true,
            report_date: reportDate,
            source_full_name: business.inspector.full_name?.raw ?? null,
            employee_id: employeeId,
            source_object_name: business.object.raw ?? business.object.value ?? null,
            entity_id: entityId,
            source_general_contractor: business.general_contractor.raw ?? null,
            general_contractor_id: generalId,
            source_subcontractor: business.subcontractor.raw ?? null,
            subcontractor_required: subcontractorRequired,
            subcontractor_id: subcontractorRequired ? subcontractorId : null,
        };
    }

    function startCleanWordReview(doc = document) {
        const get = id => doc.getElementById(id);
        const client = createCleanWordReviewClient();
        const elements = {
            file: get('wordFile'),
            parse: get('parseWordButton'),
            status: get('wordReviewStatus'),
            reportCard: get('reportCard'),
            errors: get('reviewErrors'),
            ack: get('reviewAcknowledgement'),
            confirm: get('confirmWordReport'),
            confirmed: get('confirmedPanel'),
        };
        let dictionaries;
        let report = null;
        let busy = false;
        const selectors = {
            employeeId: get('employeeChoice'),
            entityId: get('entityChoice'),
            generalContractorId: get('generalContractorChoice'),
            subcontractorId: get('subcontractorChoice'),
        };

        function addOption(select, value, label) {
            select.add(new Option(label, String(value)));
        }

        function fillSelect(select, placeholder, items, valueOf, labelOf, selectedValue) {
            select.replaceChildren(new Option(placeholder, ''));
            for (const item of items) addOption(select, valueOf(item), labelOf(item));
            select.value = selectedValue == null ? '' : String(selectedValue);
        }

        function resetConfirmation(clearAcknowledgement = true) {
            elements.confirmed.hidden = true;
            elements.confirmed.removeAttribute('data-confirmed');
            if (clearAcknowledgement) elements.ack.checked = false;
            if (report) get('reportState').textContent = 'ОЖИДАЕТ ПРОВЕРКИ';
            updateConfirmEnabled();
        }

        function selectedValues() {
            return {
                reportDate: get('reportDate').value,
                employeeId: selectors.employeeId.value,
                entityId: selectors.entityId.value,
                generalContractorId: selectors.generalContractorId.value,
                subcontractorId: selectors.subcontractorId.value,
            };
        }

        function updateConfirmEnabled() {
            if (!report || busy) {
                elements.confirm.disabled = true;
                return;
            }
            try {
                buildCleanWordConfirmation(report, selectedValues(), elements.ack.checked);
                elements.confirm.disabled = false;
            } catch (_) {
                elements.confirm.disabled = true;
            }
        }

        function hint(id, status, source) {
            const target = get(id);
            target.className = status === 'exact' || status === 'alias' ? 'match-ok' : 'needs-review';
            target.textContent = source;
        }

        function showErrors(errors) {
            elements.errors.replaceChildren();
            if (!errors.length) {
                elements.errors.hidden = true;
                return;
            }
            const title = doc.createElement('strong');
            title.textContent = 'Требуют внимания:';
            const list = doc.createElement('ul');
            for (const error of errors) {
                const item = doc.createElement('li');
                item.textContent = error.message;
                list.append(item);
            }
            elements.errors.append(title, list);
            elements.errors.hidden = false;
        }

        function renderReport(item) {
            report = item;
            elements.reportCard.hidden = false;
            elements.confirmed.hidden = true;
            get('reportFilename').textContent = item.filename;
            get('sourceDate').textContent = item.report_date_raw || 'Не распознана';
            get('sourceEmployee').textContent = item.full_name || 'Не распознано';
            get('sourceObject').textContent = item.object_name || 'Не распознано';
            get('sourceGeneralContractor').textContent = item.general_contractor || 'Не распознан';
            get('sourceSubcontractor').textContent = item.subcontractor || 'Не указан';
            get('reportDate').value = item.report_date || '';

            fillSelect(
                selectors.employeeId,
                'Выберите сотрудника',
                dictionaries.employees,
                employee => employee.id,
                employee => employee.position_name
                    ? `${employee.full_name} — ${employee.position_name}`
                    : employee.full_name,
                item.employee_id,
            );
            fillSelect(
                selectors.entityId,
                'Выберите объект или подобъект',
                dictionaries.entities,
                entity => entity.entity_id,
                entity => entity.parent_entity_id
                    ? `${entity.parent_name || 'Объект'} → ${entity.name}`
                    : entity.name,
                item.entity_id,
            );
            fillSelect(
                selectors.generalContractorId,
                'Выберите генподрядчика',
                dictionaries.organizations,
                organization => organization.id,
                organization => organization.name,
                item.general_contractor_id,
            );
            const subcontractorRequired =
                item.business_data.subcontractor_match.status !== 'not_applicable';
            fillSelect(
                selectors.subcontractorId,
                subcontractorRequired ? 'Выберите субподрядчика' : 'Не указан / не применяется',
                dictionaries.organizations,
                organization => organization.id,
                organization => organization.name,
                item.subcontractor_id,
            );
            hint('employeeMatchHint', item.business_data.employee_match.status,
                `Распознавание: ${item.business_data.employee_match.status}`);
            hint('entityMatchHint', item.business_data.object_match.status,
                `Распознавание: ${item.business_data.object_match.status}`);
            hint('generalContractorHint', item.business_data.general_contractor_match.status,
                `Распознавание: ${item.business_data.general_contractor_match.status}`);
            hint('subcontractorHint', item.business_data.subcontractor_match.status,
                `Распознавание: ${item.business_data.subcontractor_match.status}`);
            elements.ack.checked = false;
            showErrors(item.errors || []);
            resetConfirmation();
        }

        function renderConfirmed(result) {
            const confirmed = result.confirmed_report;
            const fields = [
                ['Дата отчёта', confirmed.report_date],
                ['Исходное ФИО из Word', confirmed.employee.source_value || '—'],
                ['Согласованный сотрудник', confirmed.employee.full_name],
                ['employee_id', confirmed.employee.employee_id],
                ['Исходное название объекта', confirmed.construction_entity.source_value || '—'],
                ['Согласованный объект', confirmed.construction_entity.parent
                    ? `${confirmed.construction_entity.parent.name} → ${confirmed.construction_entity.name}`
                    : confirmed.construction_entity.name],
                ['entity_id', confirmed.construction_entity.entity_id],
                ['Исходный генподрядчик', confirmed.general_contractor.source_value || '—'],
                ['Согласованный генподрядчик', confirmed.general_contractor.name],
                ['Исходный субподрядчик', confirmed.subcontractor.source_value || '—'],
                ['Согласованный субподрядчик', confirmed.subcontractor.name || 'Не указан'],
            ];
            const list = get('confirmedFields');
            list.replaceChildren();
            for (const [label, value] of fields) {
                const term = doc.createElement('dt');
                const description = doc.createElement('dd');
                term.textContent = label;
                description.textContent = String(value);
                list.append(term, description);
            }
            elements.confirmed.hidden = false;
            elements.confirmed.dataset.confirmed = 'true';
            get('reportState').textContent = 'ПОДТВЕРЖДЁН · БЕЗ СОХРАНЕНИЯ';
            elements.status.textContent = 'Промежуточный результат подтверждён; постоянные данные не записывались.';
            elements.status.className = 'database-status ok';
        }

        elements.file.addEventListener('change', () => {
            elements.parse.disabled = !elements.file.files?.length || busy;
        });
        elements.parse.addEventListener('click', async () => {
            const file = elements.file.files?.[0];
            if (!file || busy) return;
            busy = true;
            elements.parse.disabled = true;
            elements.status.textContent = 'Разбираем документ и проверяем clean-start справочники…';
            elements.status.className = 'database-status';
            try {
                renderReport(await client.parse(file));
                elements.status.textContent = 'Разбор готов. Проверьте исходные значения и согласуйте обязательные поля.';
                elements.status.className = 'database-status warning';
            } catch (error) {
                elements.status.textContent = error.message;
                elements.status.className = 'database-status error';
            } finally {
                busy = false;
                elements.parse.disabled = !elements.file.files?.length;
                updateConfirmEnabled();
            }
        });
        for (const control of [
            get('reportDate'),
            ...Object.values(selectors),
        ]) {
            control.addEventListener('change', resetConfirmation);
            control.addEventListener('input', resetConfirmation);
        }
        elements.ack.addEventListener('change', () => resetConfirmation(false));
        get('clearWordReport').addEventListener('click', () => {
            report = null;
            elements.reportCard.hidden = true;
            elements.confirmed.hidden = true;
            elements.errors.hidden = true;
            elements.file.value = '';
            elements.parse.disabled = true;
            elements.status.textContent = 'Выберите Word-файл для разбора.';
            elements.status.className = 'database-status';
        });
        elements.confirm.addEventListener('click', async () => {
            if (!report || busy) return;
            let payload;
            try {
                payload = buildCleanWordConfirmation(report, selectedValues(), elements.ack.checked);
            } catch (error) {
                elements.status.textContent = error.message;
                elements.status.className = 'database-status error';
                return;
            }
            busy = true;
            updateConfirmEnabled();
            try {
                renderConfirmed(await client.confirm(payload));
            } catch (error) {
                elements.status.textContent = error.message;
                elements.status.className = 'database-status error';
            } finally {
                busy = false;
                updateConfirmEnabled();
            }
        });

        (async () => {
            try {
                await client.verify();
                dictionaries = await client.dictionaries();
                elements.status.textContent = 'Изолированное clean-start окружение подтверждено. Выберите файл.';
                elements.status.className = 'database-status ok';
            } catch (error) {
                elements.status.textContent = error.message;
                elements.status.className = 'database-status error';
                elements.file.disabled = true;
            }
        })();
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {createCleanWordReviewClient, buildCleanWordConfirmation};
    } else {
        startCleanWordReview();
    }
    root.createCleanWordReviewClient = createCleanWordReviewClient;
    root.buildCleanWordConfirmation = buildCleanWordConfirmation;
})(typeof window !== 'undefined' ? window : globalThis);
