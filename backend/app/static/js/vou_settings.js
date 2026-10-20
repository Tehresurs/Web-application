(() => {
    'use strict';
    const form = document.getElementById('vouSettingsForm');
    const nav = document.getElementById('settingsNavButton');
    const status = document.getElementById('vouSettingsStatus');
    if (!form || !nav) return;
    const button = form.querySelector('button[type="submit"]');
    const fields = ['contract_number', 'contract_date', 'contract_revision',
                    'customer_signer_name', 'contractor_signer_name'];
    let ready = false;
    async function request(options) {
        const response = await fetch('/api/vou/settings', options);
        const body = await response.json();
        if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось сохранить реквизиты ВОУ');
        return body.item;
    }
    function display(item) {
        for (const field of fields) form.elements[field].value = item[field] || '';
        status.textContent = item.configured ? 'Реквизиты сохранены.' :
            'Реквизиты не заполнены полностью: ' + item.missing_fields.join(', ');
    }
    nav.addEventListener('click', async () => {
        showMainSection(document.getElementById('settingsPage'), nav);
        if (ready) return;
        button.disabled = true;
        status.textContent = 'Загрузка реквизитов…';
        try { display(await request()); ready = true; }
        catch (error) { status.textContent = error.message; }
        finally { button.disabled = !ready; }
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!ready) return;
        button.disabled = true;
        const values = Object.fromEntries(fields.map(field => [field, form.elements[field].value.trim()]));
        values.contract_date ||= null;
        try { display(await request({method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)})); }
        catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    });
})();
