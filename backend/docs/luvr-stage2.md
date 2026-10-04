# ЛУВР, этап 2: история сотрудников и архив

Выполнено 02.10.2026. Миграция **006_luvr_history.sql** применена, backend перезапущен на http://127.0.0.1:8000. Этап 3 не реализовывался.

## Реализованное поведение

Создано хранение непрерывной истории перемещений, периодов болезни, согласованных исключений и ручных значений отдельных дней. История связана с `employees.id` и не ограничивается месяцем. ARRIVAL и DEPARTURE независимы: противоположные или граничные события не создаются. Повторные события одного типа допустимы.

В employees добавлены:

| Поле | PostgreSQL | NULL | DEFAULT |
|---|---|---|---|
| dismissal_date | date | да | нет |
| is_archived | boolean | нет | false |
| archived_at | timestamp without time zone | да | нет |

Увольнение и архивирование — отдельные явные операции. Заполнение даты увольнения не архивирует сотрудника. Архивирование сохраняет ID, назначения, Журнал, подтверждённые факты и всю историю ЛУВР. Восстановление очищает только архивное состояние/дату архивирования; dismissal_date сохраняется. Повторный запрос архивирования не меняет первоначальный archived_at.

## Изменённые файлы

- `app/main.py` — регистрация router истории, dismissal_date, фильтры сотрудников, archive/restore и запрет DELETE.
- `app/repositories/employees.py` — чтение/сохранение новых полей, фильтрация архива и атомарное обновление архивного состояния; блокировка старой функции удаления.
- `app/templates/processing.html` — фильтр «Действующие / Архив», дата увольнения, служебный блок истории, подключение JS.
- `app/static/js/processing.js` — интеграция истории и архива в существующую карточку и список сотрудников.
- `app/static/css/main.css` — компактное оформление служебной истории и кнопок архива.
- `tests/test_references.py` — применение миграции 006 в изолированных схемах тестов.

## Созданные файлы

- `app/database/migrations/006_luvr_history.sql`.
- `app/database/migrate_luvr_history.py`.
- `app/repositories/luvr_history.py`.
- `app/api/luvr_history.py` — FastAPI router и Pydantic schemas в существующем стиле проекта.
- `app/static/js/luvr_history.js`.
- `app/static/js/employee_archive.js`.
- `tests/test_luvr_history.py` — 29 backend-тестов.
- `tests/test_luvr_history.cjs` — 15 JavaScript-тестов истории.
- `tests/test_employee_archive.cjs` — 11 JavaScript-тестов архива, включая реальные обработчики processing.js.
- `docs/luvr-stage2.md` — этот отчёт.

Перечень относится к этому этапу. В рабочем дереве уже были изменения предыдущих этапов: они сохранены.

## API

Общий префикс истории: `/api/employees/{employee_id}/luvr`.

| Путь после префикса | Операции |
|---|---|
| `/movements` | GET, POST |
| `/movements/{item_id}` | PATCH, DELETE |
| `/sick-periods` | GET, POST |
| `/sick-periods/{item_id}` | PATCH, DELETE |
| `/duration-exceptions` | GET, POST |
| `/duration-exceptions/{item_id}` | PATCH, DELETE |
| `/day-overrides` | GET, POST (явный UPSERT по сотруднику и дате) |
| `/day-overrides/{item_id}` | DELETE |

GET возвращает `{status:"ok", items:[...]}` в хронологическом порядке; POST/PATCH — `{status:"ok", item:{...}}`; DELETE записи истории — `{status:"ok", id:..., deleted:true}`. Нельзя изменить/удалить запись другого сотрудника, подставив чужой item_id: возвращается 404. employee_id проверяется и защищается FK.

Все GET истории принимают `date_from`, `date_to`. Для событий фильтр включает весь конечный местный день, включая доли секунды. Для болезни/исключений возвращаются периоды, пересекающиеся с диапазоном, включая открытую болезнь, начавшуюся раньше диапазона. Без фильтров возвращается вся история.

PATCH изменяет только переданные поля и проверяет итоговую запись под блокировкой строки. Обязательные поля нельзя очистить, nullable-поля можно очистить явным null. Пустой PATCH не принимается. Перенос записи между сотрудниками не поддерживается.

POST override — осознанная замена ручного значения по `(employee_id, work_date)`; ID существующей записи сохраняется. Удаление override удаляет только ручное значение, не создавая автоматического результата календаря.

Дополнены существующие API сотрудников:

- `GET /api/employees` — действующие (`is_archived=false`).
- `GET /api/employees?archived=true` — архивные.
- `GET /api/employees?include_archived=true` — все, включая архив (этот параметр имеет приоритет над archived).
- POST/PATCH сотрудника принимают `dismissal_date`; пропуск нового поля сохраняет значение при PATCH, явный null очищает дату. Старый контракт обязательного ФИО сохранён.
- `POST /api/employees/{employee_id}/archive` — архивировать без тела запроса.
- `POST /api/employees/{employee_id}/restore` — восстановить без тела запроса.

Archive/restore возвращают `{status:"ok", item:{id,full_name,is_archived,archived_at,dismissal_date}}`. Несуществующий сотрудник — HTTP 404. Архивирование не меняет должность, нормативы, НРС, дату увольнения и связанные строки.

### Решение по DELETE сотрудника

По окончательному согласованному решению **физическое удаление отключено для всех сотрудников**, независимо от связей. Старый маршрут `DELETE /api/employees/{employee_id}` сохранён для совместимости, помечен deprecated в Swagger и всегда возвращает HTTP 409:

```json
{
  "status": "error",
  "message": "Физическое удаление сотрудников отключено. Используйте действие «В архив». История сотрудника будет сохранена."
}
```

Маршрут вызывает защитную функцию repository, которая сразу возвращает конфликт, не открывая соединение и не выполняя DELETE. Частичного удаления и каскадных изменений при таком запросе быть не может. Обработчик подтверждён тестом, запрещающим любое обращение к соединению БД.

Старый `employee_assignments ON DELETE CASCADE` и `daily_control_results ON DELETE RESTRICT` оставлены как были. Новые исторические FK используют RESTRICT. Ни один обычный пользовательский путь не выполняет физическое удаление сотрудника; ручные административные SQL-операции вне приложения этим этапом не переопределяются.

### Примеры запросов

Самостоятельный заезд — POST `/api/employees/17/luvr/movements`:

```json
{
  "movement_type": "ARRIVAL",
  "transport_type": "SELF",
  "event_datetime": "2026-09-20T07:59:00",
  "departure_station": null,
  "arrival_station": null,
  "source_file": null
}
```

Дата/время сохраняются без изменения. Модель и API принимают RAIL для будущего импорта, но UI создаёт только SELF; загрузки файлов и парсера билетов нет. SELF с ненулевым source_file отклоняется. ISO-время с `Z` или смещением не принимается: API ожидает местные дату и время без зоны.

Болезнь — POST `/api/employees/17/luvr/sick-periods`:

```json
{"date_from":"2026-10-10","date_to":null,"comment":"Болезнь продолжается"}
```

Закрытие болезни — PATCH соответствующего item_id: `{"date_to":"2026-10-15"}`. Болезнь не создаёт и не изменяет перемещения.

Исключение — POST `/api/employees/17/luvr/duration-exceptions`:

```json
{"exception_type":"SHIFT","date_from":"2026-10-01","date_to":"2026-10-05","comment":"Продление согласовано"}
```

Ручной день — POST `/api/employees/17/luvr/day-overrides`:

```json
{"work_date":"2026-10-01","value":"HALF","comment":"Ручное согласование"}
```

Примеры не создавались в рабочей БД. Значения FULL/HALF/TRAVEL/OFF_SHIFT/DOWNTIME/DISMISSED/EMPTY хранятся кодами, без float. «Болеет» не является допустимым override. DISMISSED в override не меняет постоянную dismissal_date.

## Минимальный интерфейс

В списке сотрудников по умолчанию открыты «Действующие». Вместо удаления — «В архив» с подтверждением. В «Архиве» отображаются ФИО, должность, дата увольнения, дата архивирования, количество объектов и «Восстановить» с подтверждением. Из архива можно открыть ту же карточку и историю, ID не меняется.

В карточке добавлена дата увольнения и раскрываемый блок «История сотрудника — ЛУВР»: перемещения, периоды болезни, согласованные исключения. В каждом разделе доступны создание, редактирование и удаление отдельных записей. Открытая болезнь показывается как «Болеет с …». RAIL отображается с источником, но ручная форма редактирует только SELF. Изменения истории сохраняются отдельными кнопками внутри блока; об этом есть пояснение. Для нового несохранённого сотрудника блок истории скрыт.

Полноценного календаря и редактора overrides в UI нет; ручные значения проверяются через документированный API/Swagger. Смена сотрудника не позволяет запоздавшему ответу сети подменить его историю. Повторный клик во время запроса не создаёт дубль запроса. Переключение действующих/архива защищено от запоздалой загрузки предыдущего списка.

## Месячный состав

`luvr_month_employees` **не создана**. Текущая архитектура не содержит месячного документа ЛУВР или операций фиксации состава. Для этого этапа постоянной истории, dismissal_date и is_archived достаточно; дублировать события по месяцам нельзя. Если следующий согласованный этап потребует сохранять ручной состав конкретного месяца, для него можно добавить отдельную сущность без изменения истории. Автоматическое включение сотрудников в новые периоды сейчас не реализовано; API действующих уже исключает архивных по умолчанию.

## Проверки

- Backend: **185 тестов прошли**, без ошибок и пропусков, включая 29 новых.
- Frontend/JavaScript: **100 тестов прошли**, без ошибок и пропусков, включая 26 новых; существующий Chrome-тест прокрутки запущен с CDP.
- Браузерный сценарий на отдельной схеме PostgreSQL: CRUD самостоятельных перемещений, точное местное время, открытая/закрытая болезнь, два исторических исключения, ручной override через API, дата увольнения, отмена подтверждения архива, архивирование, доступ к истории, восстановление и отдельная очистка даты увольнения — успешно.
- В Chrome Network подтверждены POST archive/restore. Физического DELETE сотрудника из UI нет. API-запросы сценария успешны; исключений JavaScript нет.
- Все связанные данные сравнены до и после архивирования/восстановления, включая назначения и Журнал. Проверки API истории архивного сотрудника проходят.
- Прокрутка проверена на 1920×1080, 1600×900, 1366×768; развёрнутый блок истории помещается в прокручиваемую область, заголовок и кнопки доступны.
- Проверены RESTRICT, FK существования сотрудника, UNIQUE ручного дня, CHECK типов/дат/комментария/источника, самостоятельное существование ARRIVAL/DEPARTURE и пересечение месяца. Проверены пограничные времена 07:59, 08:00, 12:59, 13:00, 19:59, 20:00 и полночь.
- Миграция проверена на первоначальное применение и повторный запуск с уже заполненной историей.
- Этап 1 продолжает работать: все три допустимые комбинации должности, запрет OBJECT + FIVE_TWO, НРС и персональные сроки покрыты прежними тестами, которые прошли.
- `git diff --check` — ошибок нет.

Команды:

```powershell
$env:DAILY_CONTROL_TEST_DB='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
$env:MODAL_CDP_URL='http://127.0.0.1:9232'
node --test tests/*.cjs
```

После перезапуска HTTP 200 получен для `/`, `/docs`, `/openapi.json`, списков сотрудников (действующие/архив/все), должностей, экипажей, объектов, подобъектов, ПО, категорий, aliases, назначений и Журнала, а также всех четырёх GET истории сотрудника. Новые маршруты и схемы присутствуют в OpenAPI; старый DELETE помечен deprecated.

## Сохранность данных

До работ зафиксированы все строки и значения существующих таблиц. Миграция применялась транзакционно, с повторным сравнением всех прежних значений. После добавления архива повторный запуск 006 также сохранил все прежние данные. Все 67 сотрудников получили `is_archived=false`, `archived_at=null`; никто автоматически не уволен и не архивирован.

| Таблица | Сохранено строк |
|---|---:|
| employees | 67 |
| positions | 19 |
| crews | 5 |
| employee_assignments | 113 |
| construction_objects | 70 |
| construction_subobjects | 2 |
| po_types | 13 |
| object_categories | 9 |
| daily_control_results | 90 |
| value_aliases | 19 |

Сравнены не только количества, но и все старые значения. Новые рабочие таблицы истории пусты: тесты выполнялись в изолированных схемах. Существующие FK сверены до/после и не изменены.

По SHA256 с началом этапа подтверждено: парсер ежедневных Word-отчётов, matching/aliases, Журнал контроля, сохранение результатов, repositories назначений/объектов/подобъектов и все старые миграции (включая 005) не изменены. Изменения общих main.py/processing.js ограничены сотрудниками и подключением истории ЛУВР. Структура подтверждённого факта контроля сохранена.

Парсер ЖД-билетов, загрузка файлов, автоматическое создание событий, календарные расчёты, индикаторы, итоги и Excel не реализованы. Работа остановлена на этапе 2.

## Структура новых таблиц и ограничения

Ниже приведена фактическая структура PostgreSQL после миграции. `id` — BIGSERIAL (в PostgreSQL bigint с sequence). `created_at` и `updated_at` получают CURRENT_TIMESTAMP; repository обновляет updated_at при редактировании/UPSERT. Время события хранится отдельно в локальном timestamp без преобразования часового пояса.

### employee_movements

| Column | PostgreSQL | Nullable | Default |
|---|---|---|---|
| id | bigint | NO | nextval('employee_movements_id_seq'::regclass) |
| employee_id | bigint | NO | - |
| movement_type | text | NO | - |
| transport_type | text | NO | - |
| event_datetime | timestamp without time zone | NO | - |
| departure_station | text | YES | - |
| arrival_station | text | YES | - |
| source_file | text | YES | - |
| created_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |

```sql
CONSTRAINT ck_movement_self_source CHECK (((transport_type <> 'SELF'::text) OR (source_file IS NULL)));
CONSTRAINT employee_movements_created_at_not_null NOT NULL created_at;
CONSTRAINT employee_movements_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT;
CONSTRAINT employee_movements_employee_id_not_null NOT NULL employee_id;
CONSTRAINT employee_movements_event_datetime_not_null NOT NULL event_datetime;
CONSTRAINT employee_movements_id_not_null NOT NULL id;
CONSTRAINT employee_movements_movement_type_check CHECK ((movement_type = ANY (ARRAY['ARRIVAL'::text, 'DEPARTURE'::text])));
CONSTRAINT employee_movements_movement_type_not_null NOT NULL movement_type;
CONSTRAINT employee_movements_pkey PRIMARY KEY (id);
CONSTRAINT employee_movements_transport_type_check CHECK ((transport_type = ANY (ARRAY['RAIL'::text, 'SELF'::text])));
CONSTRAINT employee_movements_transport_type_not_null NOT NULL transport_type;
CONSTRAINT employee_movements_updated_at_not_null NOT NULL updated_at;
```

### employee_sick_periods

| Column | PostgreSQL | Nullable | Default |
|---|---|---|---|
| id | bigint | NO | nextval('employee_sick_periods_id_seq'::regclass) |
| employee_id | bigint | NO | - |
| date_from | date | NO | - |
| date_to | date | YES | - |
| comment | text | YES | - |
| created_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |

```sql
CONSTRAINT ck_sick_period_dates CHECK (((date_to IS NULL) OR (date_to >= date_from)));
CONSTRAINT employee_sick_periods_created_at_not_null NOT NULL created_at;
CONSTRAINT employee_sick_periods_date_from_not_null NOT NULL date_from;
CONSTRAINT employee_sick_periods_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT;
CONSTRAINT employee_sick_periods_employee_id_not_null NOT NULL employee_id;
CONSTRAINT employee_sick_periods_id_not_null NOT NULL id;
CONSTRAINT employee_sick_periods_pkey PRIMARY KEY (id);
CONSTRAINT employee_sick_periods_updated_at_not_null NOT NULL updated_at;
```

### employee_duration_exceptions

| Column | PostgreSQL | Nullable | Default |
|---|---|---|---|
| id | bigint | NO | nextval('employee_duration_exceptions_id_seq'::regclass) |
| employee_id | bigint | NO | - |
| exception_type | text | NO | - |
| date_from | date | NO | - |
| date_to | date | NO | - |
| comment | text | NO | - |
| created_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |

```sql
CONSTRAINT ck_duration_exception_dates CHECK ((date_to >= date_from));
CONSTRAINT employee_duration_exceptions_comment_check CHECK ((comment ~ '[^[:space:]]'::text));
CONSTRAINT employee_duration_exceptions_comment_not_null NOT NULL comment;
CONSTRAINT employee_duration_exceptions_created_at_not_null NOT NULL created_at;
CONSTRAINT employee_duration_exceptions_date_from_not_null NOT NULL date_from;
CONSTRAINT employee_duration_exceptions_date_to_not_null NOT NULL date_to;
CONSTRAINT employee_duration_exceptions_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT;
CONSTRAINT employee_duration_exceptions_employee_id_not_null NOT NULL employee_id;
CONSTRAINT employee_duration_exceptions_exception_type_check CHECK ((exception_type = ANY (ARRAY['SHIFT'::text, 'OFF_SHIFT'::text])));
CONSTRAINT employee_duration_exceptions_exception_type_not_null NOT NULL exception_type;
CONSTRAINT employee_duration_exceptions_id_not_null NOT NULL id;
CONSTRAINT employee_duration_exceptions_pkey PRIMARY KEY (id);
CONSTRAINT employee_duration_exceptions_updated_at_not_null NOT NULL updated_at;
```

### employee_luvr_day_overrides

| Column | PostgreSQL | Nullable | Default |
|---|---|---|---|
| id | bigint | NO | nextval('employee_luvr_day_overrides_id_seq'::regclass) |
| employee_id | bigint | NO | - |
| work_date | date | NO | - |
| value | text | NO | - |
| comment | text | YES | - |
| created_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | NO | CURRENT_TIMESTAMP |

```sql
CONSTRAINT employee_luvr_day_overrides_created_at_not_null NOT NULL created_at;
CONSTRAINT employee_luvr_day_overrides_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT;
CONSTRAINT employee_luvr_day_overrides_employee_id_not_null NOT NULL employee_id;
CONSTRAINT employee_luvr_day_overrides_id_not_null NOT NULL id;
CONSTRAINT employee_luvr_day_overrides_pkey PRIMARY KEY (id);
CONSTRAINT employee_luvr_day_overrides_updated_at_not_null NOT NULL updated_at;
CONSTRAINT employee_luvr_day_overrides_value_check CHECK ((value = ANY (ARRAY['FULL'::text, 'HALF'::text, 'TRAVEL'::text, 'OFF_SHIFT'::text, 'DOWNTIME'::text, 'DISMISSED'::text, 'EMPTY'::text])));
CONSTRAINT employee_luvr_day_overrides_value_not_null NOT NULL value;
CONSTRAINT employee_luvr_day_overrides_work_date_not_null NOT NULL work_date;
CONSTRAINT uq_employee_luvr_day UNIQUE (employee_id, work_date);
```

## SQL: 006_luvr_history.sql

```sql
-- Continuous employee history, independent of calendar months.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS dismissal_date DATE;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITHOUT TIME ZONE;

CREATE TABLE IF NOT EXISTS employee_movements (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('ARRIVAL','DEPARTURE')),
    transport_type TEXT NOT NULL CHECK (transport_type IN ('RAIL','SELF')),
    event_datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    departure_station TEXT,
    arrival_station TEXT,
    source_file TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_movement_self_source CHECK (transport_type <> 'SELF' OR source_file IS NULL)
);
CREATE INDEX IF NOT EXISTS ix_employee_movements_time ON employee_movements(employee_id,event_datetime,id);

CREATE TABLE IF NOT EXISTS employee_sick_periods (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    date_from DATE NOT NULL,
    date_to DATE,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_sick_period_dates CHECK (date_to IS NULL OR date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS ix_employee_sick_dates ON employee_sick_periods(employee_id,date_from);

CREATE TABLE IF NOT EXISTS employee_duration_exceptions (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    exception_type TEXT NOT NULL CHECK (exception_type IN ('SHIFT','OFF_SHIFT')),
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    comment TEXT NOT NULL CHECK (comment ~ '[^[:space:]]'),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_duration_exception_dates CHECK (date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS ix_employee_exception_dates ON employee_duration_exceptions(employee_id,date_from);

CREATE TABLE IF NOT EXISTS employee_luvr_day_overrides (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    work_date DATE NOT NULL,
    value TEXT NOT NULL CHECK (value IN ('FULL','HALF','TRAVEL','OFF_SHIFT','DOWNTIME','DISMISSED','EMPTY')),
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_employee_luvr_day UNIQUE (employee_id,work_date)
);
```

```powershell
.\.venv\Scripts\python.exe -m app.database.migrate_luvr_history
```
