# Плановое количество должностей

12.10.2026.

Миграция **021_position_planned_count.sql** добавляет `positions.planned_count INTEGER NOT NULL DEFAULT 0` с CHECK `planned_count >= 0`. Выполнена штатным модулем `python -m app.database.migrate_position_planned_count`. Транзакционный runner проверил неизменность всех прежних полей. В рабочей БД 18 должностей, новое значение у всех — 0. БД не сбрасывалась.

Использованы действующие GET/POST/PATCH `/api/positions` и фактически подключённый repository `app/repositories/employees.py`. POST без значения использует 0; PATCH без поля сохраняет прежнее значение. API отклоняет отрицательные, дробные, null, bool, строки и числа вне диапазона INTEGER. Остальные поля должностей сохранены.

В существующие список и форму должностей добавлены колонка и числовой input «Плановое количество». Сохранение использует прежние обработчик и API.

Изменены:
- `app/main.py`
- `app/repositories/employees.py`
- `app/static/js/processing.js`
- `app/static/css/main.css`
- `app/templates/processing.html`
- `tests/test_references.py` — миграция изолированных тестовых схем.

Созданы:
- `app/database/migrations/021_position_planned_count.sql`
- `app/database/migrate_position_planned_count.py`
- `tests/test_position_planned_count.py`
- `tests/browser/position_planned_count.cjs`
- этот отчёт.

Проверки: **468 backend-тестов**, **194 frontend-теста** прошли. Новые проверки покрывают создание, изменение, чтение, пропуск поля, невалидные значения, ограничения БД, сохранность прежних данных и повторную миграцию. Браузер на изолированной схеме: создание с 12, перезагрузка, изменение на 7, повторная перезагрузка и отображение колонки — пройдено, JS-ошибок нет. Тестовая схема удалена. Рабочий GET возвращает новое поле.

ЛУВР, матрица, билеты, парсеры и их расчёты в рамках задачи не менялись.
