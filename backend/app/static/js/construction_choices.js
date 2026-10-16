/* Selection values are typed identities; legacy IDs are never synthesized. */
const ConstructionChoices = (() => {
    const hierarchy = item => item?.current_hierarchy || item || {};
    const entityId = item => item?.entity_id ?? item?.current_hierarchy?.entity_id;
    const parentId = item => hierarchy(item).parent_entity_id ?? null;
    const value = item => entityId(item) != null ? `entity:${entityId(item)}`
        : String(item?.object_id ?? item?.id ?? '');
    const archived = item => Boolean(item?.is_archived || item?.parent_is_archived ||
        hierarchy(item).is_archived || hierarchy(item).effectively_archived || hierarchy(item).parent?.is_archived);
    const label = item => {
        const h = hierarchy(item);
        const name = h.name || item.name || item.control_item_name || item.object_name || 'Объект';
        const parent = h.parent?.name || (parentId(item) != null ? item.object_name : null);
        return `${parent ? `${parent} → ` : ''}${name}${archived(item) ? ' (архив)' : ''}`;
    };
    function reference(selected, parent = false) {
        if (!selected) return {object_id: null};
        const match = String(selected).match(/^(entity:)?([1-9]\d*)$/);
        if (!match) throw new Error('Выберите объект из списка');
        return {[match[1] ? (parent ? 'parent_entity_id' : 'entity_id') : 'object_id']: Number(match[2])};
    }
    function parents(items, excluded = null) {
        return items.filter(item => parentId(item) === null && !archived(item) &&
            (!excluded || value(item) !== value(excluded)));
    }
    function selectedValue(items, selected) {
        if (!selected) return '';
        if (entityId(selected) != null) return value(selected);
        const found = items.find(item => {
            const h = hierarchy(item);
            return selected.subobject_id != null ? h.legacy_subobject_id === selected.subobject_id
                : selected.object_id != null && h.legacy_object_id === selected.object_id;
        });
        return found ? value(found) : Object.prototype.hasOwnProperty.call(selected, 'object_id')
            ? String(selected.object_id ?? '') : value(selected);
    }
    function options(items, selected = null, {parentsOnly = false, excluded = null} = {}) {
        const selectedKey = selectedValue(items, selected);
        const eligible = parentsOnly ? parents(items, excluded) : items.filter(item =>
            !archived(item) && hierarchy(item).is_active !== false);
        const rows = [...new Map(eligible.map(item => [value(item),
            {value: value(item), label: label(item), item}])).values()];
        if (selectedKey && !rows.some(row => row.value === selectedKey)) {
            const item = items.find(item => value(item) === selectedKey) || selected;
            rows.push({value: selectedKey, label: label(item), item, historical: true});
        }
        rows.sort((a, b) => a.label.localeCompare(b.label, 'ru', {numeric: true}));
        return {rows, selected: selectedKey};
    }
    function fill(select, items, selected = null, config = {}) {
        const result = options(items, selected, config);
        select.replaceChildren(new Option(config.placeholder || 'Выберите объект', ''));
        for (const row of result.rows) {
            const option = new Option(row.label, row.value);
            // Retain an unavailable historical choice without offering it as a new parent.
            option.disabled = Boolean(config.parentsOnly && row.historical);
            select.add(option);
        }
        select.value = result.selected;
        return result;
    }
    async function load(request, roots = null) {
        roots ??= (await request('/api/objects')).items || [];
        // The old schema has only the original object selector contract.
        if (!roots.some(item => entityId(item) != null)) return roots;
        const children = (await request('/api/subobjects?include_inactive=true')).items || [];
        return [...roots, ...children];
    }
    return {hierarchy, entityId, parentId, value, archived, label, reference, parents, selectedValue, options, fill, load};
})();
if (typeof module !== 'undefined') module.exports = ConstructionChoices;
