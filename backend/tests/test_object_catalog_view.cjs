const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const template = fs.readFileSync('app/templates/processing.html', 'utf8');
const processing = fs.readFileSync('app/static/js/processing.js', 'utf8');

test('test profile exposes the four object catalog views without replacing categories or PO tabs', () => {
    const viewTabs = template.match(/<div class="object-view-tabs ui-tabs"[\s\S]*?<\/div>/);
    assert.ok(viewTabs);
    for (const label of ['Все объекты', 'Самостоятельные объекты', 'Подобъекты', 'Архив']) {
        assert.ok(viewTabs[0].includes(label), `missing ${label} view`);
    }
    assert.match(template, /id="categoriesTab"/);
    assert.match(template, /id="poTab"/);
    assert.match(template, /class="ui-input employee-search" id="objectSearchInput"/);
});

test('test catalog archive actions use archive and restore endpoints', () => {
    assert.match(processing, /const archiveButton = event\.target\.closest\("\.archive-object-directory"\)/);
    assert.match(processing, /\/api\/\$\{kind\}\/\$\{item\.id\}\/\$\{action\}/);
    assert.match(processing, /method:\s*"POST"/);
});

test('test catalog dialogs show read-only codes and retain names for preview-only conversion', () => {
    assert.match(template, /id="objectDirectoryCodeInput" readonly/);
    assert.match(template, /id="subobjectDirectoryCode" readonly/);
    assert.match(template, /id="identityPromoteName"/);
    assert.match(template, /id="identityPromoteCode" readonly/);
    assert.match(template, /id="identityStandaloneName"/);
    assert.match(template, /id="identityStandaloneCode" readonly/);
    assert.match(template, /Предварительная проверка не сохраняет изменения/);
});
