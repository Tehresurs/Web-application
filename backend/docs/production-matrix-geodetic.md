# Производственная матрица — геодезический контроль

09.10.2026. Добавлен `GEODETIC` — «Геодезический контроль».

## Хранение и доступность

Миграция `020_geodetic_control.sql` расширяет CHECK-ограничения режимов в `production_assignment_items` и `production_matrix_overrides`. Создана небольшая таблица разрешения `production_control_mode_positions` с FK на должность. В рабочей БД привязана существующая должность «Инженер СК (Геодезические работы)», ID 9. Название используется только при первоначальной привязке, далее проверяется ID: переименование не отключает разрешение. Сама должность и её поля не изменены.

Это разрешение выбора и значение по умолчанию для нового назначения. Конкретный режим хранится в существующей строке назначения либо датированной корректировке; INSPECTION/OPERATIONAL остаются доступны. CAMERAL по-прежнему вычисляется автоматически и запрещён как ручное значение.

При POST нового объектного назначения отсутствие `initial_control_mode` означает GEODETIC только для разрешённой должности. Явные INSPECTION/OPERATIONAL и null сохраняются как переданы. PATCH существующего события не подставляет новый режим автоматически. GET истории назначений дополнен `allowed_control_modes` и `default_control_mode`.

API проверяет разрешение при записи назначения и корректировки. Политика читается с блокировкой сотрудника при записи; источник, объект, период и версия проверяются прежними механизмами. В результате матрицы каждой объектной ячейке передаётся `allowed_control_modes`. Frontend использует этот список для dropdown. Уже сохранённый исторический режим остаётся видимым даже после изменения должности сотрудника, но недоступный режим нельзя выбрать заново.

Миграция применена дважды в одной проверочной транзакции. Контрольные суммы строк positions, employees, employee_assignments, employee_movements, rail_tickets, daily_control_results, production_assignment_changes, production_assignment_items и production_matrix_overrides совпали до/после. Протокол: `C:/Projects/geodetic-migration-result.json`.

## Изменённые файлы

- `app/api/production_assignments.py`
- `app/api/production_matrix_overrides.py`
- `app/repositories/production_assignments.py`
- `app/repositories/production_matrix_overrides.py`
- `app/repositories/production_matrix.py`
- `app/services/production_matrix.py` — только метаданные допустимых режимов для интерфейса.
- `app/static/js/production_matrix.js`
- `app/templates/processing.html` — версия JS.
- `tests/test_production_matrix.py`
- `tests/test_production_matrix.cjs`
- `tests/browser/production_matrix.cjs`

Новые файлы:

- `app/database/migrations/020_geodetic_control.sql`
- `app/database/migrate_geodetic_control.py`
- `app/repositories/production_control_modes.py`
- `docs/production-matrix-geodetic.md`

## Проверки

- Полный backend: **449 тестов прошли**, изолированные схемы PostgreSQL; `C:/Projects/geodetic-backend.log`.
- Полный frontend: **192 теста прошли**, без пропусков; `C:/Projects/geodetic-frontend.log`.
- Целевые проверки: создание с GEODETIC по умолчанию; явные прежние режимы и null; PATCH без автоматической подстановки; запрет GEODETIC другой должности; автоматический CAMERAL; независимое наследование режима/категории через месяц; новый факт и смена объекта; объединение строк; повторная миграция и сохранность исторических данных; сохранение разрешения при переименовании должности.
- Браузер на свежей изолированной БД (`PM_GEODETIC_TEST=1`): выбор GEODETIC, сохранение и повторная загрузка матрицы, русская подпись в деталях, POST нового объекта без режима и получение GEODETIC, переключение месяцев, существующие PLAN/FACT/CAMERAL, корректировки, конфликты и навигация. Ошибок JavaScript нет.
- `git diff --check` без ошибок содержимого.

## Ограничения

Отдельной формы создания датированных производственных назначений в существующем интерфейсе пока нет. Значение по умолчанию реализовано в действующем API новых назначений и выдаётся его GET; в матрице GEODETIC выбирается через существующий dropdown корректировки. Новая форма и экран настройки разрешений не создавались.

Исторические факты с пустым режимом автоматически не заполняются. Правила FACT/PLAN и наследования не изменены: корректировка FACT относится к своей дате, PLAN наследуется до следующего основания или границы периода. Word-парсер, ЛУВР, билеты, движения и подтверждённые факты не изменены; визуальный стиль сохранён.
