# ЛУВР, этап 1: справочники

Выполнено 02.10.2026. Миграция применена к рабочей БД, backend перезапущен на http://127.0.0.1:8000. Этап 2 не реализовывался.

## Файлы этого этапа

Изменены:

- `app/main.py` — новые поля существующих Pydantic requests и передача в repository.
- `app/repositories/employees.py` — существующие CRUD должностей/сотрудников, проверки и JOIN параметров должности.
- `app/templates/processing.html` — поля форм, подключение помощника, обновление версии ресурсов.
- `app/static/js/processing.js` — подключение новых полей только в формах должностей/сотрудников.
- `app/static/css/main.css` — компактные параметры должности и блок в форме сотрудника.
- `tests/test_references.py` — новая миграция в изолированной тестовой схеме.

Созданы:

- `app/database/migrations/005_luvr_directories.sql`.
- `app/database/migrate_luvr_directories.py` — явный транзакционный запуск миграции.
- `app/static/js/luvr_directories.js` — поведение новых полей форм.
- `tests/test_luvr_directories.py` — 11 backend-тестов с PostgreSQL.
- `tests/test_luvr_directories.cjs` — 8 JavaScript-тестов.
- `docs/luvr-stage1.md` — этот отчёт.

В рабочем дереве до начала этапа уже были другие изменения. Сравнение SHA256 с началом этого этапа подтвердило изменение только пяти перечисленных существующих файлов внутри `app`; новые файлы перечислены отдельно. Старые миграции не изменены.

## Фактическая структура БД

Исходная структура совпала с заданием. Все старые столбцы, связи, значения и значения по умолчанию сохранены. Новые столбцы nullable, без DEFAULT и без автоматического заполнения.

`positions`:

| Поле | PostgreSQL | NULL | Примечание |
|---|---|---|---|
| id | bigint | нет | прежний PK, sequence |
| name | varchar | нет | прежнее поле |
| action_description | text | да | прежнее поле |
| created_at | timestamp without time zone | нет | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | нет | CURRENT_TIMESTAMP |
| specialty | text | да | новое |
| work_location | text | да | OBJECT / OFFICE |
| work_schedule | text | да | SHIFT / FIVE_TWO |

`employees`:

| Поле | PostgreSQL | NULL | Примечание |
|---|---|---|---|
| id | bigint | нет | прежний PK, sequence |
| full_name | varchar | нет | прежнее поле |
| position_id | bigint | да | прежняя связь с positions |
| phone | varchar | да | прежнее поле |
| crew_id | bigint | да | прежняя связь с crews |
| created_at | timestamp without time zone | нет | CURRENT_TIMESTAMP |
| updated_at | timestamp without time zone | нет | CURRENT_TIMESTAMP |
| nrs_number | text | да | произвольная строка |
| max_shift_days | integer | да | положительное целое |
| max_off_shift_days | integer | да | положительное целое |

`specialty`, `work_location`, `work_schedule` не добавлены в employees: ответы API получают их JOIN по `position_id`.

## API и правила

Обновлены существующие маршруты:

- `GET /api/positions`, `POST /api/positions`, `PATCH /api/positions/{position_id}`.
- `GET /api/employees`, `POST /api/employees`, `PATCH /api/employees/{employee_id}`.

Пути, существующие поля и форма ответов сохранены. GET возвращает `{status:"ok", items:[...]}`. POST/PATCH должности возвращает `{status:"ok", item:{...}}`, сотрудника — `{status:"ok", id:...}`. Данные сотрудника вместе с параметрами должности возвращаются в GET списка. DELETE не изменён.

У PATCH сохранён прежний контракт: название должности / ФИО обязательны. Пропущенные **новые** поля сохраняют прежние значения; явный `null` очищает их, если это не нарушает правило OBJECT → SHIFT. Семантика старых полей не менялась.

Пример POST/PATCH должности:

```json
{
  "name": "Инженер СК",
  "action_description": "Строительный контроль",
  "specialty": "ОС/СТ",
  "work_location": "OBJECT",
  "work_schedule": "SHIFT"
}
```

Пример POST/PATCH сотрудника (position_id — ID выбранной должности):

```json
{
  "full_name": "Иванов Иван Иванович",
  "position_id": 1,
  "phone": null,
  "crew_id": null,
  "nrs_number": "НРС / 007-А",
  "max_shift_days": 45,
  "max_off_shift_days": 21
}
```

Это примеры, а не записи в рабочей БД; 45/21 не являются значениями по умолчанию.

Backend и PostgreSQL проверяют допустимые значения места/графика и обязательный SHIFT для OBJECT. OBJECT + FIVE_TWO и OBJECT + NULL отклоняются. OFFICE допускает оба графика; незаполненные параметры старых записей допустимы. Backend возвращает 400 при несовместимой комбинации и 422 при неверном типе/значении Pydantic-поля.

Сроки — `null` или целое от 1 до 2147483647 (диапазон PostgreSQL INTEGER). Backend не принимает дроби, bool и строки вместо целого; PostgreSQL CHECK исключает ноль и отрицательные числа. НРС хранится строкой без проверки выдуманного формата.

## Интерфейс

В форме должности появились специальность, место и график. OBJECT автоматически выбирает SHIFT и блокирует выбор другого графика; OFFICE разрешает оба. Старое «Описание действий» сохранено. В списке новые параметры компактно отображаются под названием.

В форме сотрудника добавлены № НРС и персональные сроки. Параметры должности отображаются только для чтения и обновляются при выборе другой должности. При SHIFT сроки видимы, при FIVE_TWO или неизвестном графике скрыты. Скрытые значения не отправляются и не стирают ранее сохранённые настройки. Никакие сроки, проценты или статусы не рассчитываются.

## Проверки

- Все backend-тесты: **156 прошли**, 0 ошибок, включая 11 новых. Команда: `$env:DAILY_CONTROL_TEST_DB='1'; .\.venv\Scripts\python.exe -m unittest discover -s tests -q`.
- JavaScript: **73 прошли** командой `node --test tests/*.cjs`; браузерный тест в этом запуске пропущен без CDP.
- Пропущенный браузерный тест отдельно выполнен с Chrome/CDP: **1 прошёл**. Итого весь существующий набор JavaScript/frontend: **74 прошли**, включая 8 новых.
- Дополнительный сценарий в настоящем Chrome с изолированной схемой PostgreSQL: создание всех трёх комбинаций должности, редактирование специальности, отображение списка, создание/редактирование сотрудника, НРС/сроки, смена должности, скрытие и сохранность сроков при 5/2 — успешно. Исключений JavaScript нет. Рабочие справочники этими тестами не изменялись.
- Прокрутка: 1920×1080, 1600×900, 1366×768; форма существующего сотрудника с 15 назначениями и девять общих модальных окон — успешно.
- `git diff --check` — ошибок нет.

После перезапуска HTTP 200 получен для `/`, `/docs`, `/openapi.json`, `/api/positions`, `/api/employees`, `/api/crews`, `/api/objects`, `/api/subobjects`, `/api/po-types`, `/api/object-categories`, `/api/employees/25/assignments`, `/api/value-aliases`, `/api/daily-control-results?date_from=2026-01-01&date_to=2026-12-31`. Новые поля проверены в OpenAPI и GET сотрудников.

## Сохранность данных и границы этапа

Перед миграцией внутри транзакции взят снимок всех строк всех public-таблиц. После миграции сравнены все старые значения; сравнение успешно. Проверены не только количества строк.

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

Идемпотентность миграции, CHECK-ограничения, nullable-совместимость и сохранность старых значений также проверены отдельными тестами в изолированной схеме.

Парсер ежедневных отчётов, matching/aliases, Журнал контроля, назначения, объекты/подобъекты, ПО, категории, подрядчики/субподрядчики, сохранение результатов и структура подтверждённого факта контроля не изменялись на этом этапе. Их отдельные файлы сверены с SHA256 до начала работ; изменения общих main.py/processing.js ограничены справочниками должностей и сотрудников. Старые регрессионные тесты прошли.

Таблицы билетов и перемещений, расчёт ЛУВР, события заезда/выезда, болезни, увольнение, индикаторы и Excel не добавлялись.

## Применённый SQL

Источник: `app/database/migrations/005_luvr_directories.sql`. Запуск: `.\.venv\Scripts\python.exe -m app.database.migrate_luvr_directories`.

Runner выполняет SQL в транзакции с advisory lock и ограничением ожидания блокировок. Миграция уже применена; повторный запуск не создаёт повторные столбцы/ограничения.

```sql
-- Additive LU VR stage 1. Existing records remain unknown (NULL), never inferred.
ALTER TABLE positions ADD COLUMN IF NOT EXISTS specialty TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS work_location TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS work_schedule TEXT;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS nrs_number TEXT;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_shift_days INTEGER;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_off_shift_days INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_work_location') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_work_location CHECK(work_location IN ('OBJECT','OFFICE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_work_schedule') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_work_schedule CHECK(work_schedule IN ('SHIFT','FIVE_TWO'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='positions'::regclass AND conname='ck_positions_object_shift') THEN
        ALTER TABLE positions ADD CONSTRAINT ck_positions_object_shift
            CHECK(work_location IS DISTINCT FROM 'OBJECT' OR work_schedule IS NOT DISTINCT FROM 'SHIFT');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='employees'::regclass AND conname='ck_employees_max_shift_days') THEN
        ALTER TABLE employees ADD CONSTRAINT ck_employees_max_shift_days CHECK(max_shift_days > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='employees'::regclass AND conname='ck_employees_max_off_shift_days') THEN
        ALTER TABLE employees ADD CONSTRAINT ck_employees_max_off_shift_days CHECK(max_off_shift_days > 0);
    END IF;
END;
$$;
```
