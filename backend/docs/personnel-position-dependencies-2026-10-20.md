# Техресурс — реестр зависимостей должности сотрудника

Дата: 20.10.2026. Только обследование; исходники не изменены.

Найдено 171 место в 49 файлах по position_id/position_name/aos_description/report_description. Расширенный поиск positions/work_schedule/work_location/requires_daily_report охватывает 533 места в 117 файлах app/scripts/tests. Это строки поиска, а не число независимых запросов или доказательство отсутствия внешнего SQL. Разобраны также общие loaders и потребители DTO. Полные совпадения и SHA256: backend/output/security/personnel_transfer_20261020T033909Z/dependencies.json и semantic_dependencies.json.

## Прямой реестр

| Файл | Строки |
|---|---|
| `backend/app/import_employees.py` | 83, 90, 104, 151, 161, 169 |
| `backend/app/main.py` | 200, 243, 244, 501, 519, 521, 526, 529, 547, 548, 550, 580, 610 |
| `backend/app/test_employee_matcher.py` | 18 |
| `backend/app/test_positions.py` | 7, 12 |
| `backend/app/api/clean_construction.py` | 357, 359, 394, 396, 446, 517, 518 |
| `backend/app/api/luvr_month.py` | 91 |
| `backend/app/api/rail_tickets.py` | 63 |
| `backend/app/database/database.sql` | 23, 24, 60, 70 |
| `backend/app/database/migrate_position_report_descriptions.py` | 9, 10, 11 |
| `backend/app/parsers/word_parser.py` | 356, 382, 433 |
| `backend/app/reports/intermediate_report.py` | 28, 86 |
| `backend/app/repositories/deployment.py` | 11, 13 |
| `backend/app/repositories/employees.py` | 36, 54, 64, 87, 102, 103, 113, 147, 153, 155, 165, 170, 174, 191, 195, 205, 206, 219, 234, 240, 242, 252, 256, 266, 279, 297, 298, 309, 318, 333, 334, 352, 382, 391, 405, 449, 462 |
| `backend/app/repositories/luvr_calendar.py` | 10, 25 |
| `backend/app/repositories/positions.py` | 24, 28, 32, 49 |
| `backend/app/repositories/production_assignments.py` | 24 |
| `backend/app/repositories/production_control_modes.py` | 12 |
| `backend/app/repositories/production_matrix.py` | 19, 22 |
| `backend/app/repositories/rail_tickets.py` | 65, 104, 105, 107 |
| `backend/app/services/clean_word_report.py` | 54, 57 |
| `backend/app/services/deployment.py` | 40, 105, 106 |
| `backend/app/services/deployment_analysis.py` | 29, 57 |
| `backend/app/services/deployment_analysis_excel.py` | 46, 100 |
| `backend/app/services/employee_matcher.py` | 42, 43, 47, 59, 60 |
| `backend/app/services/luvr_export_table.py` | 67 |
| `backend/app/services/luvr_month.py` | 45 |
| `backend/app/services/matrix_dk.py` | 35, 74 |
| `backend/app/services/processing_service.py` | 84 |
| `backend/app/services/production_matrix.py` | 160, 165, 191, 192 |
| `backend/app/services/vou_data.py` | 150, 180, 182, 183, 194, 200, 221, 234, 235, 255 |
| `backend/app/services/vou_dk_display.py` | 25, 26, 30, 35, 38, 39, 45 |
| `backend/app/services/vou_layout.py` | 89 |
| `backend/app/static/js/clean_word_review.js` | 196, 197 |
| `backend/app/static/js/crew_memberships.js` | 40, 58 |
| `backend/app/static/js/deployment_analysis.js` | 4, 29, 32 |
| `backend/app/static/js/employee_absences.js` | 41 |
| `backend/app/static/js/employee_card.js` | 107, 130 |
| `backend/app/static/js/employee_workspace.js` | 6, 24, 41 |
| `backend/app/static/js/luvr_month.js` | 138, 184 |
| `backend/app/static/js/luvr_sort.js` | 1 |
| `backend/app/static/js/processing.js` | 638, 2075, 2076, 2085, 2182, 2230 |
| `backend/app/static/js/production_matrix.js` | 135, 147 |
| `backend/app/static/js/rail_employee.js` | 19, 38 |
| `backend/app/static/js/rail_tickets.js` | 43 |
| `backend/app/static/js/vou_archive.js` | 63 |
| `backend/app/database/migrations/014_position_report_descriptions.sql` | 2, 3 |
| `backend/app/database/migrations/020_geodetic_control.sql` | 2, 12 |
| `backend/scripts/auth_closed_command_prototype.py` | 45 |
| `backend/scripts/auth_command_proof_prototype.py` | 103 |

## Разбор цепочек и требуемых изменений

| Цепочка | Нынешняя зависимость | Датированный контракт |
|---|---|---|
| Карточка / список / редактирование | employees.get/list/update, employee_card/employee_workspace/processing.js | current_position(today), планы отдельно; ordinary PATCH не должен менять должность мимо transfer |
| Отсутствия | employee_absences.js повторно отправляет position_id/crew_id; update_employee безусловно их присваивает | Удалить этот обход при согласованном переходе. Изменение отсутствия не устанавливает основную должность |
| Создание из Word/билета | processing.js, rail_employee.js, employee_matcher, rail_tickets._employee | Начальная должность — отдельный контракт, не перевод. Подсказка текущей должности не заменяет должность на дату документа |
| Импорт / ручная запись | import_employees, app/test_positions, repositories/positions | Все писатели должны использовать baseline/batch/справочные закрытые команды. Импорт сейчас одна TX; не запускался |
| Общий календарь | repositories/luvr_calendar.CALENDAR_SELECT → services/luvr_calendar/luvr_duration → luvr_month | work_location/work_schedule/name/specialty сегодня одни на весь месяц. Нужен общий датированный loader, а не исправление заголовка |
| ЛУВР / Excel / сортировка | api/luvr_month.MonthEmployee, luvr_month.py/js, luvr_sort.js, luvr_export_table.py | Должность по дню; месячные строки по периодам, один дневной ресурс сотрудника. DTO одной position_name на весь месяц недостаточно |
| Производственная матрица | production_matrix.get_inputs + CALENDAR_SELECT + _inputs + policy → calculate_month → JS | POSITION_RULE/basis_id, requires_daily_report, допустимость ДК и подпись строки должны учитывать day. Описания АОС/отчёта не добавлять в матрицу |
| Контроль и назначения | production_control_modes.policy, production_assignments._inputs/save | GEODETIC и ограничения проверять на дату/период. Существующие подтверждённые факты и назначения не переписывать автоматически |
| ДК | matrix_dk.eligible/is_dk_day | Точное имя должности берётся из текущего CALENDAR_SELECT. История/версии требуют нового контекста, dirty/nonce и того же eligible с единым датированным loader. HR-образец этого не делает |
| Ежедневные документы / Word | employee_matcher → processing_service DTO → word_parser/intermediate_report/clean_word_review | Идентификация сотрудника по ID отдельно от должности на report_date. Неизвестная дата не допускает подстановку сегодняшней должности |
| Расстановка | deployment.get_report(target) → matrix + repositories/deployment.employee_details(ids) | target передать также в employee_details: сейчас там текущие report_description/equipment_description. Сортировка по должности на target |
| Аналитика / Excel | deployment_analysis.analyze_day, deployment_analysis_excel | working[eid]=current pid; planned_count тоже без истории. Датировать должность; отдельно решить версионирование плана штата |
| ВОУ | vou_data внутри цикла day использует employee.position_id, а не должность дня; vou_dk_display тоже | Группировка по дню/версии должности, включая пустые ДК-строки. Разные должности/описания не сливать одним ключом |
| АОС-описание | vou_data/vou_dk_display → vou_layout | aos_description из версии справочника на дату. Отдельный полный АОС-генератор со сквозной историчностью не установлен; внешние инструменты требуют отдельного аудита |
| Справочник | employees.rename_position, PositionRequest; database.sql, migration014, migrate_position_report_descriptions | name/action_description/specialty/schedule/location/descriptions/requires_daily_report/equipment требуют версий. Физический DELETE с FK SET NULL несовместим с историей |
| Экипажи / UI связей | crew_memberships.js показывает position_name | Состав сохраняется; отображение должности датировать, не превращать перевод в изменение экипажа |
| Архив ВОУ | vou_archive.js выводит сохранённый документ | Сохранять snapshot/version; ретроправка — явный новый выпуск, не замена UUID/файла |
| Прототипы 44/45 | employee_read возвращает current position_id | Это эксперименты, не API приложения; будущий DTO также датировать. Старая HMAC-подпись не покрывает HR |
| Clean-start | api/clean_construction, services/clean_word_report | SQL public/отдельный профиль; не переносить миграцию business-схемы автоматически |

Каталог подтвердил employees.position_id → positions ON DELETE SET NULL и production_control_mode_positions.position_id → positions ON DELETE RESTRICT. Все 57 FK и 19 пользовательских триггеров сохранены в before.json. Наличие исторической SQL-миграции/функции не выдается за дополнительный действующий runtime-путь.
