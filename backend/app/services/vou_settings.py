"""Current VOU requisites. Report generation must snapshot this returned value."""
from datetime import date
from psycopg.rows import dict_row
from app.database.db import get_connection

FIELDS = ('contract_number', 'contract_date', 'contract_revision',
          'customer_signer_name', 'contractor_signer_name')
LABELS = dict(zip(FIELDS, ('Номер договора', 'Дата договора', 'Редакция договора',
                         'Ф.И.О. подписанта заказчика', 'Ф.И.О. подписанта исполнителя')))


def assert_target(conn):
    actual = conn.execute('SELECT current_database(), current_schema()').fetchone()
    if tuple(actual) != ('ai_excel_agent_test', 'test_construction_identity_stage46'):
        raise RuntimeError('Настройки ВОУ доступны только в конфигурации 8001')


def normalize(values):
    if set(values) != set(FIELDS):
        raise ValueError('Передайте все пять полей реквизитов ВОУ')
    result = {}
    for field in FIELDS:
        value = values[field]
        if field == 'contract_date':
            if value in (None, ''):
                value = None
            elif isinstance(value, str):
                value = date.fromisoformat(value).isoformat()
            elif type(value) is date:
                value = value.isoformat()
            else:
                raise ValueError('Некорректная дата договора')
        else:
            if not isinstance(value, str):
                raise ValueError(f'{LABELS[field]}: требуется текст')
            value = value.strip()
            if len(value) > 500 or any(ord(ch) < 32 for ch in value):
                raise ValueError(f'{LABELS[field]}: недопустимое значение')
        result[field] = value
    return result


def view(values):
    item = normalize({field: values.get(field, None if field == 'contract_date' else '')
                      for field in FIELDS})
    item['missing_fields'] = [LABELS[field] for field in FIELDS if not item[field]]
    item['configured'] = not item['missing_fields']
    return item


def get_settings():
    with get_connection() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        assert_target(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT * FROM vou_settings WHERE id=1')
            return view(cur.fetchone() or {})


def save_settings(values):
    item = normalize(values)
    with get_connection() as conn:
        assert_target(conn)
        conn.execute("""INSERT INTO vou_settings
          (id,contract_number,contract_date,contract_revision,customer_signer_name,contractor_signer_name)
          VALUES (1,%s,%s,%s,%s,%s)
          ON CONFLICT (id) DO UPDATE SET contract_number=excluded.contract_number,
          contract_date=excluded.contract_date,contract_revision=excluded.contract_revision,
          customer_signer_name=excluded.customer_signer_name,
          contractor_signer_name=excluded.contractor_signer_name,updated_at=now()""",
          tuple(item[field] for field in FIELDS))
    return view(item)


def require_configured(values):
    item = view(values)
    if not item['configured']:
        raise ValueError('Заполните реквизиты Отчета ВОУ: ' + ', '.join(item['missing_fields']))
    return {field: item[field] for field in FIELDS}
