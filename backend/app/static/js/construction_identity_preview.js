function constructionIdentityEligibility(entities, entityId, parentEntityId, nameOverride) {
    const entity = entities.find(item => String(item.entity_id) === String(entityId));
    if (!entity) return {allowed: false, reason: "Сущность не найдена в текущей иерархии. Обновите список."};
    const children = entities.filter(item => String(item.parent_entity_id) === String(entity.entity_id));
    if (children.length) return {allowed: false, reason: "У сущности есть подобъекты. Сначала упорядочите структуру."};

    const targetParentId = parentEntityId == null ? null : Number(parentEntityId);
    if (targetParentId === entity.entity_id) return {allowed: false, reason: "Нельзя выбрать эту сущность родителем самой себе."};
    if (targetParentId === null) {
        if (entity.parent_entity_id == null) return {allowed: false, reason: "Сущность уже является самостоятельным объектом."};
    } else {
        if (entity.parent_entity_id != null) return {allowed: false, reason: "Преобразовать в подобъект можно только самостоятельный объект."};
        const parent = entities.find(item => Number(item.entity_id) === targetParentId);
        if (!parent || parent.parent_entity_id != null || parent.is_archived) {
            return {allowed: false, reason: "Выберите существующий самостоятельный объект вне архива."};
        }
    }

    const normalize = value => String(value || "").trim().toLocaleLowerCase("ru")
        .replaceAll("ё", "е").replace(/№\s+/g, "№").replace(/[\s\u00a0]+/g, " ");
    const targetName = nameOverride == null ? entity.name : nameOverride;
    const duplicate = entities.some(item => String(item.entity_id) !== String(entity.entity_id)
        && (item.parent_entity_id ?? null) === targetParentId
        && normalize(item.name) === normalize(targetName));
    if (duplicate) return {allowed: false, reason: "На целевом уровне уже есть запись с таким названием."};
    return {allowed: true, reason: "Предварительная проверка пройдена. Преобразование не выполнено."};
}

function createConstructionIdentityPreview({document: doc = document, getKnownEntities, request = fetch,
    enablePromote = false, enableStandalone = false, cleanStart = false, onSaved = async () => {}, confirmOperation = message => window.confirm(message)}) {
    const apiBase = cleanStart ? '/api/clean-construction-entities' : '/api/construction-entities';
    const get = id => doc.getElementById(id);
    const promoteModal = get("identityPromoteModal");
    const standaloneModal = get("identityStandaloneModal");
    if (!promoteModal || !standaloneModal) return {open() {}};

    const parent = get("identityPromoteParent");
    const promoteResult = get("identityPromoteResult");
    const standaloneResult = get("identityStandaloneResult");
    const promoteName = get("identityPromoteName");
    const standaloneName = get("identityStandaloneName");
    const promoteCode = get("identityPromoteCode");
    const standaloneCode = get("identityStandaloneCode");
    let current = null;
    let busy = false;

    function hideResults() {
        for (const result of [promoteResult, standaloneResult]) {
            result.hidden = true;
            result.textContent = "";
        }
    }

    function close() {
        if (busy) return;
        promoteModal.hidden = true;
        standaloneModal.hidden = true;
        current = null;
        hideResults();
    }

    function open(operation, item) {
        if (busy) return;
        if (operation !== "promote" && operation !== "standalone") return;
        const hierarchy = item?.current_hierarchy || item || {};
        const entityId = item?.entity_id ?? hierarchy.entity_id;
        if (entityId == null) return;
        current = {operation, entityId, name: hierarchy.name || item.name || "Объект",
            version: hierarchy.version,
            code: hierarchy.code ?? item.code ?? item.object_code ?? item.code_value ?? item.construction_code ?? ""};
        hideResults();
        promoteModal.hidden = operation !== "promote";
        standaloneModal.hidden = operation !== "standalone";
        if (operation === "promote") {
            if (promoteName) promoteName.value = current.name;
            if (promoteName) promoteName.readOnly = enablePromote;
            get('identityPromoteCheck').textContent = enablePromote ? 'Преобразовать' : 'Проверить допустимость';
            if (promoteCode) promoteCode.value = current.code;
            parent.replaceChildren();
            const placeholder = doc.createElement("option");
            placeholder.value = "";
            placeholder.textContent = "Выберите родительский объект";
            parent.append(placeholder);
            const known = getKnownEntities().map(value => value.current_hierarchy || value);
            const choices = known.filter(value => value.parent_entity_id == null && !value.is_archived && value.is_active !== false
                && String(value.entity_id) !== String(entityId));
            choices.sort((a, b) => a.name.localeCompare(b.name, "ru", {numeric: true, sensitivity: "base"}));
            for (const choice of choices) {
                const option = doc.createElement("option");
                option.value = String(choice.entity_id);
                option.textContent = choice.name;
                parent.append(option);
            }
        } else {
            if (standaloneName) standaloneName.value = current.name;
            if (standaloneName) standaloneName.readOnly = enableStandalone;
            get('identityStandaloneCheck').textContent = enableStandalone ? 'Сделать самостоятельным объектом' : 'Проверить допустимость';
            if (standaloneCode) standaloneCode.value = current.code;
        }
    }

    async function check() {
        if (!current || busy) return;
        const result = current.operation === "promote" ? promoteResult : standaloneResult;
        const selectedParent = current.operation === "promote" ? parent.value : null;
        if (current.operation === "promote" && !selectedParent) {
            result.textContent = "Выберите новый родительский объект.";
            result.hidden = false;
            return;
        }
        busy = true;
        const operation = {...current};
        const button = get(current.operation === "promote" ? "identityPromoteCheck" : "identityStandaloneCheck");
        button.disabled = true;
        result.hidden = true;
        try {
            const response = await request(apiBase, {method: "GET"});
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || "Не удалось проверить текущую иерархию.");
            const entities = data.items || [];
            const proposedName = current.operation === "promote" ? promoteName?.value : standaloneName?.value;
            const eligibility = constructionIdentityEligibility(entities, current.entityId, selectedParent, proposedName);
            if ((operation.operation === 'promote' ? enablePromote : enableStandalone) && eligibility.allowed) {
                const source = entities.find(item => Number(item.entity_id) === Number(operation.entityId));
                if (!Number.isInteger(operation.version) || source?.version !== operation.version) {
                    throw new Error('Иерархия изменилась. Закройте окно и обновите список перед повторным подтверждением.');
                }
                const target = entities.find(item => Number(item.entity_id) === Number(selectedParent));
                if (!confirmOperation(operation.operation === 'promote'
                    ? `Преобразовать «${operation.name}» в подобъект «${target.name}»?`
                    : `Сделать «${operation.name}» самостоятельным объектом?`)) return;
                const environmentResponse = await request(apiBase + '/environment', {method: 'GET'});
                const environmentData = await environmentResponse.json();
                const environment = environmentData.item;
                if (!environmentResponse.ok || environment?.profile !== 'test' ||
                    (cleanStart ? environment.contract !== 'entity_id' || environment.schema !== 'public' :
                    environment.database !== 'ai_excel_agent_test' || environment.schema !== 'test_construction_identity_stage46')) {
                    throw new Error('Тестовая БД и схема не подтверждены. Преобразование остановлено.');
                }
                const savedResponse = await request(`${apiBase}/${operation.entityId}/hierarchy`, {
                    method: 'PATCH', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({parent_entity_id: selectedParent == null ? null : Number(selectedParent), version: operation.version, confirmed: true}),
                });
                const saved = await savedResponse.json();
                if (!savedResponse.ok) throw new Error(saved.message || saved.detail || 'Не удалось выполнить преобразование.');
                // Never retry a committed mutation if refreshing the tree fails.
                current = null;
                try { await onSaved(saved.item); promoteModal.hidden = true; standaloneModal.hidden = true; }
                catch (_) { throw new Error('Преобразование сохранено. Не удалось обновить дерево — обновите страницу.'); }
                return;
            }
            result.textContent = eligibility.reason;
            result.hidden = false;
            result.className = eligibility.allowed ? "category-parent-note" : "category-parent-note ui-error";
        } catch (error) {
            result.textContent = error.message || "Не удалось проверить текущую иерархию.";
            result.hidden = false;
            result.className = "category-parent-note ui-error";
        } finally {
            busy = false;
            button.disabled = false;
        }
    }

    get("identityPromoteCheck").addEventListener("click", check);
    get("identityStandaloneCheck").addEventListener("click", check);
    for (const modal of [promoteModal, standaloneModal]) {
        for (const button of modal.querySelectorAll("[data-identity-close]")) button.addEventListener("click", close);
        modal.addEventListener("click", event => { if (event.target === modal) close(); });
    }
    return {open, close, check};
}

if (typeof module !== "undefined") module.exports = {constructionIdentityEligibility, createConstructionIdentityPreview};
