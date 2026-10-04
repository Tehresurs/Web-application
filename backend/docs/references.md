# Этап 3: подобъекты и aliases

Все операции доступны в `/docs` и `/openapi.json`. Используются существующие
таблицы этапа 2 и SQL-функция `normalize_known_value`; миграции при запуске не выполняются.

| Метод | URL | Назначение |
|---|---|---|
| GET | `/api/subobjects?object_id=15` | Активные подобъекты, необязательный фильтр родителя |
| GET | `/api/subobjects?include_inactive=true` | Включить неактивные для последующей реактивации |
| GET | `/api/subobjects/{id}` | Одна запись, включая неактивную |
| POST | `/api/subobjects` | Создать подобъект |
| PATCH | `/api/subobjects/{id}` | Изменить name и/или is_active |
| GET | `/api/value-aliases?entity_type=employee&source_value=Кецких Игорь Валерьевич` | Точный нормализованный поиск; оба фильтра необязательны |
| GET | `/api/value-aliases/{id}` | Соответствие с данными цели |
| POST | `/api/value-aliases` | Создать или вернуть идентичное соответствие |
| PATCH | `/api/value-aliases/{id}` | Явно изменить только target_id |
| DELETE | `/api/value-aliases/{id}` | Удалить соответствие, сохранив цель |

Успех: HTTP 200. Список: `{"status":"ok","items":[...]}`.
Запись: `{"status":"ok","item":{...}}`.
POST alias дополнительно возвращает `created`: true для новой записи, false для повтора.
DELETE возвращает `{"status":"ok","id":1,"deleted":true}`.

Пример POST `/api/subobjects` (ID и названия в ответах условные):

```json
{"object_id":15,"name":"Подъезд к кусту скважин №55"}
```

```json
{"status":"ok","item":{"id":101,"object_id":15,"name":"Подъезд к кусту скважин №55","is_active":true,"object_name":"Куст скважин №55"}}
```

Пример PATCH `/api/subobjects/101`:

```json
{"is_active":false}
```

Пример POST `/api/value-aliases`:

```json
{"entity_type":"employee","source_value":"Кецких Игорь Валерьевич","target_id":17}
```

```json
{"status":"ok","created":true,"item":{"id":8,"entity_type":"employee","source_value":"Кецких Игорь Валерьевич","normalized_source_value":"кецких игорь валерьевич","target_id":17,"target_name":"Кецких Игорь Валерьевич","object_id":null,"object_name":null,"target_exists":true,"target_is_active":null}}
```

Пример PATCH `/api/value-aliases/8`: `{"target_id":18}`.
Исходное написание сохраняется. Для subobject ответ содержит родителя
`object_id`, `object_name` и `target_is_active`.

Конфликт (HTTP 409):

```json
{"status":"error","message":"Для этого значения уже существует другое соответствие."}
```

Отсутствующий родитель/target/ID: HTTP 404. Неактивный target-подобъект: HTTP 400.
Ошибки Pydantic (пустое значение, неверный тип, лишние поля, пустой PATCH): HTTP 422.
Нормализованные дубли подобъектов запрещены внутри одного родителя, включая неактивные.
Уникальные индексы обеспечивают защиту от конкурентного создания дублей.
Физический DELETE aliases соответствует существующим справочникам проекта.

Repository для следующего этапа:

- `find_subobject_exact(object_id, name)` — запись или None, включая неактивные.
- `find_subobjects_by_name(name, object_id=None)` — список активных точных совпадений;
  сохраняет неоднозначность при одинаковых названиях у разных родителей.
- `resolve_value_alias(entity_type, source_value)` — запись с целью и родителем или None.
  Удалённые цели и неактивные подобъекты не разрешаются; GET сохраняет их видимость
  через `target_exists` и `target_is_active` для явного исправления.

Aliases не подключены к парсеру, matching или сохранению отчётов. Автоматического обучения нет.

Проверки из backend (PostgreSQL-тесты создают отдельные схемы и откатывают их):

```powershell
$env:DAILY_CONTROL_TEST_DB='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_journal.cjs tests/test_report_save.cjs
```
