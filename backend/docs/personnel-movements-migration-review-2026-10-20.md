> **Обновление 20.10.2026:** по отдельному разрешению 033/034 применены, 8001 перезапущен. Сохранение остаётся заблокированным действующими проверками; подробности и новые проверки — [рабочая установка](personnel-movements-working-install-2026-10-20.md). Указания ниже «миграция не применена» описывают прежнее состояние.

﻿# Перемещение сотрудников — структура миграции для согласования

Дата: 20.10.2026. Проект C:/Projects/excel-ai-agent-8001.
Цель возможного будущего применения: ai_excel_agent_test/test_construction_identity_stage46.

**Рабочая миграция не выполнена. Перечень ниже подготовлен для предварительного рассмотрения. Установка не выполняется при старте приложения.**

## Новые таблицы

Используется уже подготовленная история из 033_personnel_transfers.sql; отдельная дублирующая история основных должностей не создаётся. 034_personnel_movements.sql добавляет только журнал И.О.

| Таблица | Поля и связи |
|---|---|
| personnel_settings | id integer PK (=1), enabled boolean=false, legacy_history_policy text=UNRESOLVED, creator_user_id bigint nullable FK auth_users ON DELETE RESTRICT, dk_context_verified/date_readers_verified boolean=false, installed_at timestamptz |
| personnel_position_definitions | id bigint identity PK, position_id bigint FK positions RESTRICT, known_from date, recorded_at timestamptz, definition jsonb, start_unknown boolean. Версии названия, специальности, графика, места работы, обязанности отчёта и описаний существующего справочника |
| personnel_position_baselines | employee_id bigint PK/FK employees RESTRICT, position_id bigint nullable FK positions RESTRICT, known_on date, observed_at timestamptz, effective_start_unknown boolean=true. known_on — дата наблюдения, не вымышленная дата первоначального назначения |
| personnel_position_state | employee_id bigint PK/FK employees RESTRICT, version integer>=0. Общая версия постоянных переводов и И.О. |
| personnel_position_events | employee_id bigint FK employees RESTRICT + version integer — составной PK; root_id uuid; kind TRANSFER/CORRECT/CANCEL; position_id bigint nullable FK positions RESTRICT; effective_on date; reason text<=2000; actor_user_id bigint FK auth_users RESTRICT; recorded_at timestamptz; source_position_id bigint nullable FK positions RESTRICT; source_on date; source_explicit boolean; retained_report_requirement boolean nullable (только true); retained_calendar_configuration jsonb |
| personnel_position_requests | actor_user_id bigint FK auth_users RESTRICT + request_id uuid — составной PK; payload/result jsonb; created_at timestamptz. Один журнал идемпотентности обеих операций |
| personnel_acting_events | employee_id bigint FK employees RESTRICT + version integer — составной PK; root_id uuid; kind ASSIGN/CHANGE_END/END/CANCEL; position_id bigint FK positions RESTRICT; starts_on/ends_on date (обязательны, конечны, начало<=конец); reason text<=2000; actor_user_id bigint FK auth_users RESTRICT; plan_change_id bigint nullable FK production_assignment_changes RESTRICT, обязателен для END; recorded_at timestamptz |

Для первичного наблюдения данные сотрудников только читаются. employees.position_id остаётся исходным наблюдением; текущая должность определяется датированной проекцией, без фонового UPDATE в день будущего перевода.

## Представления и функции

Три представления: personnel_position_current_orders, personnel_position_periods, personnel_acting_current. Периоды основной должности полуоткрытые [начало, следующее начало); последний день И.О. включён в его период. Дата инженерного возвращения — следующий календарный день.

Функции 033: personnel_position_at, personnel_capture_position_definition, personnel_new_employee, personnel_guard_direct_position, personnel_position_command, personnel_transfer, personnel_review_transfer, personnel_transfer_with_source. Функции 034: personnel_acting_at, personnel_acting_command. SQL фиксирован; универсального исполнения клиентских SQL/имён таблиц нет. SECURITY DEFINER использует фиксированный search_path, PUBLIC EXECUTE отозван. Новые таблицы/представления и последовательность определений также закрыты для PUBLIC.

Три триггера добавляются к существующим таблицам: AFTER INSERT OR UPDATE positions сохраняет версию описания; AFTER INSERT employees сохраняет исходное наблюдение; BEFORE UPDATE OF employees.position_id отклоняет прямую смену основной должности. Существующие импорты/админские инструменты с прямым UPDATE position_id потребуют адаптации до включения.

Столбцы существующих 41 таблицы не удаляются и не переопределяются. Пользователи, роли, пароли и их назначения не создаются. Штатное завершение И.О. после активации создаёт записи только через существующий production_assignments.save в production_assignment_changes/production_assignment_items. Старые планы не заменяются скрыто. Неполные реквизиты плана продолжают диагностироваться действующей матрицей.

## Правила, которые важно проверить перед включением

- Для перевода исходная должность определяется накануне даты операции. Если она неизвестна, требуется явный выбор из существующего справочника. Это подтверждает сведения на указанную дату, не придумывает начало первой должности.
- Последующие переводы сохраняются. Несовместимость с записанной исходной должностью следующего перевода даёт отказ; исправление/отмена также проверяют этот случай.
- График и место работы сохраняются от исходного кадрового состояния, а не автоматически принимаются из новой должности. Экипаж/категории/старые факты/движения не меняются.
- В проверенном справочнике ID 16 «Инженер СК ТА» имеет requires_daily_report=false. Только для нового перевода в эту должность из состояния с обязательным отчётом сохраняется прежняя обязанность, как прямо требует ТЗ. Справочник и существующие сотрудники ТА этим правилом не переписываются.
- Пересекающиеся И.О. одного сотрудника отклоняются. Исправления срока/отмена используют прежнюю выделенную полномочность review; общий SYSTEM_TECHNICIAN не получает права отмены. OFFICE_MANAGER имеет только чтение/экспорт.
- Авторизация доверяет проверенной HTTP-сессии существующего AuthService. Числовые actor/session_id не являются криптографическим доказательством для произвольного SQL владельца БД. Новый минимальный SQL-runtime и расширение HMAC-контекста ДК здесь не внедрены.

## Применение и откат

1. До рабочего применения отдельно согласовать миграцию и включение. Нужны действующий пользовательский контекст, проверенный расширенный контекст ДК и проверка всех оставшихся датированных читателей; флаги готовности нельзя выставлять вместо этих работ.
2. Сделать свежий backup и проверить его восстановление в отдельной БД. Проверить точные имена целевой БД/схемы и отсутствие уже установленной другой версии personnel_settings. Действующий установщик отказывается перезаписывать установленную историю.
3. В согласованном окне применить 033 и затем 034 явным установщиком, оставив enabled=false и оба verification-флага false. Нужны ограниченные lock_timeout и проверка исходных 41 таблицы. Это план, не разрешение исполнения.
4. Предактивационный откат подготовлен в backend/docs/sql/rollback_personnel_movements_pre_activation.sql, отдельно от каталога миграций. Он работает одной транзакцией, без CASCADE, проверяет disabled и пустые журналы. После появления операций отказывается удалять данные. На изолированной копии проверяются удаление только новых объектов, сохранность 41 исходной таблицы и повторная установка.
5. После использования функции не удалять её историю. Откат приложения требует совместимой с историей версии и запрета новых кадровых записей. Полное восстановление backup не является автоматическим откатом: оно способно потерять последующие рабочие изменения и требует отдельного решения.

**Включение в рабочей системе сейчас не предлагается. Новый кадровый контекст ещё не связан с серверным HMAC/SEALED; в проверенной рабочей auth_users нет аккаунтов, действующий 8001 остаётся прежним процессом. Эти условия нельзя обходить созданием аккаунтов, ручной сменой флагов или ослаблением авторизации.**
