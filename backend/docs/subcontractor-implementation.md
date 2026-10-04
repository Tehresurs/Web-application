Реализация субподрядчика, 30.09.2026.

Подтверждённый отчёт сохраняет один факт: дата, инженер, объект/подобъект, основное ПО, необязательный субподрядчик, категория. Оба поля организаций ссылаются на `po_types`. Назначение и категория определяются только по основному ПО и родительскому объекту.

Изменённые файлы относительно начала этой задачи (пути от `backend`):

- `app/api/daily_control.py` — фильтр журнала `subcontractor_id`.
- `app/api/known_values.py` — тип alias `subcontractor` в схемах API.
- `app/repositories/daily_control.py` — одно сохранение с обеими ролями, дедупликация, имена и фильтры журнала.
- `app/repositories/objects.py` — понятный отказ при удалении организации, используемой фактом контроля.
- `app/repositories/value_aliases.py` — отдельный тип соответствий с target в `po_types`.
- `app/services/daily_control_service.py` — проверка присутствия субподрядчика, выбранного target и сохранение одного факта.
- `app/services/po_matcher.py` — общий exact/alias/fuzzy для двух ролей; обработка отсутствия значения.
- `app/services/processing_service.py` — результат анализа субподрядчика, сохранение `raw_subcontractor`.
- `app/static/js/processing.js` — отдельная роль, выбор/создание/запоминание, отсутствие без замечаний, назначение только основного ПО.
- `app/static/js/report_save.js` — оба ID организаций в запросе, назначение только основного ПО.
- `app/static/js/journal.js` — шестая колонка и фильтр субподрядчика.
- `app/templates/processing.html` — фильтр и подписи полей.
- `tests/test_daily_control.py` — актуализированы сценарии одного факта и атомарного отката.
- `tests/test_references.py`, `tests/test_known_values.py` — миграции в изолированных тестовых схемах.
- `tests/test_processing.py` — независимость тестов парсинга от содержимого рабочего справочника.
- `tests/test_alias_ui.cjs` — отдельный тип alias.
- `tests/test_journal_ui.cjs` — шесть колонок, пустое значение, фильтр и переходы по истории.

Созданные файлы:

- `app/database/migrations/004_subcontractor.sql`.
- `app/database/migrate_subcontractor.py`.
- `tests/test_subcontractor.py`.
- `tests/test_subcontractor_ui.cjs`.
- `docs/subcontractor-implementation.md`.

Миграция `004_subcontractor.sql` применена к рабочей PostgreSQL 18.6. Для другой установки запускать после миграций 001–003:

```powershell
.\.venv\Scripts\python.exe -m app.database.migrate_subcontractor
```

Миграция выполняется транзакционно, с блокировкой таблицы, ограничениями ожидания и предварительной проверкой дублей и ссылок. Новый уникальный индекс создаётся до снятия прежнего ограничения. Повторное выполнение безопасно. При конфликте транзакция откатывается; записи автоматически не исправляются.

Итоговая структура `daily_control_results`:

| Поле | Тип / назначение |
|---|---|
| id | BIGSERIAL, PK |
| report_date | DATE NOT NULL |
| employee_id | BIGINT NOT NULL, FK employees |
| object_id | BIGINT NOT NULL, FK construction_objects, родитель |
| subobject_id | BIGINT NULL, FK construction_subobjects |
| po_id | BIGINT NOT NULL, FK po_types, основное ПО |
| subcontractor_id | BIGINT NULL, FK po_types, ON DELETE RESTRICT |
| category_id | BIGINT NOT NULL, FK object_categories |
| source_file | TEXT NOT NULL, непустое имя исходного файла |
| source_sha256 | CHAR(64) NOT NULL, отпечаток исходного документа |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP |

Добавлен индекс `ix_daily_control_subcontractor`. Итоговое ограничение `uq_daily_control_fact`:

```sql
UNIQUE NULLS NOT DISTINCT (
    report_date, employee_id, object_id, subobject_id,
    po_id, subcontractor_id, category_id
)
```

Разные субподрядчики, отсутствие субподрядчика и разные подобъекты различают факты. Полный повтор не создаёт запись. `source_file` не входит в бизнес-ключ. Для уже сохранённого `source_sha256` возвращаются прежние результаты без повторной интерпретации, включая старые отчёты, сохранённые двумя строками.

В `value_aliases` добавлен допустимый `entity_type='subcontractor'`. Target проверяется в `po_types`; GET и resolve возвращают имя организации. `normalize_known_value()` использует для новой роли правила ПО: регистр, ё/е, пробелы, кавычки «»/". Правила остальных типов не изменены. Ключ `(entity_type, normalized_source_value)` сохранён: alias ПО не применяется к субподрядчику. Повтор с тем же target возвращает существующий alias; другой target даёт HTTP 409. Явное изменение target остаётся через PATCH; исходный текст автоматически не меняется.

Цепочка анализа: исходная строка → отсутствие → exact в `po_types` → alias `subcontractor` → прежний fuzzy организаций (`SequenceMatcher`, порог 0.75, до пяти кандидатов) → решение пользователя. Никакого автоматического обучения. Создание новой организации использует существующий POST `/api/po-types` и не создаёт alias.

Примеры ниже иллюстративные; тестовые организации не добавлялись в рабочую БД.

| Исходная строка | Условия | Результат |
|---|---|---|
| NULL, пустая строка, пробелы, `-`, `—`, `–`, `−`, `‑`, `‒` | Отсутствие | `subcontractor_id=null`, `not_applicable`, замечаний нет |
| ` ооо "елка" ` | В справочнике `ООО «Ёлка»`, id=27 | exact: `found`, id=27 |
| `ООО "Строй Мантаж"` | Явный alias subcontractor → id=27 | alias: `found`, id=27, имя из справочника |
| `ООО СтройМантаж` | В справочнике `ООО СтройМонтаж`, alias отсутствует | `similar`, пользователь выбирает кандидата |
| `XYZ` | Нет exact, alias и кандидатов выше порога | `new`, требуется решение |

Пример явного запоминания:

```http
POST /api/value-aliases
Content-Type: application/json

{"entity_type":"subcontractor","source_value":"ООО \"Строй Мантаж\"","target_id":27}
```

Пример сохранения одного отчёта с ПО и субподрядчиком:

```json
{
  "path": "C:/reports/report.docx",
  "employee_id": 12,
  "object_id": 15,
  "subobject_id": 8,
  "general_contractor_id": 15,
  "subcontractor_id": 27,
  "assignments": {"15": 42}
}
```

POST `/api/daily-control-results` проверяет исходный Word, существование выбранной организации, принадлежность подобъекта и назначение №42. При дате 24.09.2026 и категории №3 создаётся одна строка:

```json
{
  "report_date": "2026-09-24",
  "employee_id": 12,
  "object_id": 15,
  "subobject_id": 8,
  "po_id": 15,
  "subcontractor_id": 27,
  "category_id": 3,
  "source_file": "report.docx"
}
```

При отсутствии субподрядчика ID можно не передавать; сохраняется NULL. Если исходная строка есть, неразрешённое состояние `similar`/`new` блокирует сохранение. Проверка `/api/daily-control-results/check` не создаёт факт. В сохранённом результате и GET журнала присутствуют `subcontractor_id` и `subcontractor_name`.

Пример фильтра:

```http
GET /api/daily-control-results?date_from=2026-09-01&date_to=2026-09-30&subcontractor_id=27
```

Журнал показывает дату, инженера, объект/подобъект, ПО, субподрядчика и категорию. Для NULL выводится «—». Пункт «Все субподрядчики» не передаёт фильтр и не создаёт запись в БД. Варианты фильтра берутся из фактов выбранного периода; фильтр сохраняется при переходе к истории инженера или объекта.

События INFO: `SUBCONTRACTOR_EXACT_MATCH`, `SUBCONTRACTOR_ALIAS_MATCH` в backend; `SUBCONTRACTOR_SELECTED` в UI и проверке сохранения; `SUBCONTRACTOR_CREATED` при создании из проверки отчёта. Отсутствие не является ошибкой.

Проверки:

- Backend: **132 теста прошли**, без пропусков, включая PostgreSQL в изолированных схемах и реальный DOCX с двумя ролями → один факт.
- JavaScript: **43 теста прошли**, без пропусков; проверки DOM и контроллеров, без заявления о ручной визуальной проверке браузера.
- Backend запущен отдельным процессом uvicorn; `/`, `/docs`, `/openapi.json`, GET журнала с фильтром и без, GET alias subcontractor — HTTP 200.
- OpenAPI содержит новый тип alias и параметр фильтра журнала.
- До/после миграции: **39 → 39** старых фактов, **85 → 85** назначений, **0 → 0** aliases. Сравнены все значения старых строк; у всех старых фактов новое поле равно NULL.
- Проверены повторяемость миграции, её откат при конфликтующих дублях, защита FK, атомарность сохранения, сохранность старого source_sha256, девять комбинаций nullable подобъекта и субподрядчика, повторные копии под другим именем.
- Хеши файлов парсера и файлов назначений совпадают со снимком перед работой. `employee_assignments`: схема, данные, repository и API не изменялись.

Команды проверки:

```powershell
$env:DAILY_CONTROL_TEST_DB='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --test tests/test_journal.cjs tests/test_journal_ui.cjs tests/test_subobject_ui.cjs tests/test_alias_ui.cjs tests/test_report_save.cjs tests/test_subcontractor_ui.cjs
```

**PARSER FILES NOT MODIFIED.** Формирование новых отчётов не реализовывалось; этап субподрядчика завершён.
