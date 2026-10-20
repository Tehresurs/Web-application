# Stage 3 route registry ? 18.10.2026

Explicit policies for isolated app.auth_protected.create_protected_app; NOT installed in app.main.
SESSION: own session. PUBLIC: login only. DENY: no authority granted. Every registered method listed separately.

| Method | Route | Permission | CSRF | Action / restriction |
|---|---|---|---|---|
| GET | `/openapi.json` | data.read | False | Read existing data/page without production changes |
| HEAD | `/openapi.json` | data.read | False | Read existing data/page without production changes |
| GET | `/docs` | data.read | False | Read existing data/page without production changes |
| HEAD | `/docs` | data.read | False | Read existing data/page without production changes |
| GET | `/docs/oauth2-redirect` | data.read | False | Read existing data/page without production changes |
| HEAD | `/docs/oauth2-redirect` | data.read | False | Read existing data/page without production changes |
| GET | `/redoc` | data.read | False | Read existing data/page without production changes |
| HEAD | `/redoc` | data.read | False | Read existing data/page without production changes |
| POST | `/api/auth/login` | PUBLIC | False | Stage 2 login, same-origin and rate limited |
| GET | `/api/auth/me` | SESSION | False | Stage 2 own session; logout requires CSRF |
| POST | `/api/auth/logout` | SESSION | True | Stage 2 own session; logout requires CSRF |
| POST | `/api/daily-control-results/review-options` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/daily-control-results/absence-rules` | data.read | False | Read existing data/page without production changes |
| DELETE | `/api/daily-control-results/absence-rules/{field}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/daily-control-results/review-category` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/daily-control-results/review-assignments/{employee_id}` | data.read | False | Read existing data/page without production changes |
| POST | `/api/daily-control-results/check` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/daily-control-results` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/daily-control-results` | data.read | False | Read existing data/page without production changes |
| GET | `/api/daily-control-results/facts/{fact_id}` | data.read | False | Read existing data/page without production changes |
| POST | `/api/daily-control-results/upload-day` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| DELETE | `/api/daily-control-results/facts/{fact_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/daily-control-results/upload-file` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/subobjects` | data.read | False | Read existing data/page without production changes |
| GET | `/api/subobjects/{subobject_id}` | data.read | False | Read existing data/page without production changes |
| POST | `/api/subobjects` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/subobjects/{subobject_id}` | data.update | True | Edit ordinary production/directory data |
| GET | `/api/value-aliases` | data.read | False | Read existing data/page without production changes |
| POST | `/api/subobjects/{subobject_id}/move/check` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/subobjects/{subobject_id}/move` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/value-aliases/{alias_id}` | data.read | False | Read existing data/page without production changes |
| POST | `/api/value-aliases` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/value-aliases/{alias_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/value-aliases/{alias_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/movements` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/movements` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/movements/{item_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/movements/{item_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/sick-periods` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/sick-periods` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/sick-periods/{item_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/sick-periods/{item_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/duration-exceptions` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/duration-exceptions` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/duration-exceptions/{item_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/duration-exceptions/{item_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/day-overrides` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/day-overrides` | data.create | True | Create ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/day-overrides/{item_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/upload` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/rail-tickets` | data.read | False | Read existing data/page without production changes |
| GET | `/api/rail-tickets/{ticket_id}` | data.read | False | Read existing data/page without production changes |
| PATCH | `/api/rail-tickets/{ticket_id}/direction` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/confirm` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/reject` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/rail-tickets/{ticket_id}/object` | data.update | True | Edit ordinary production/directory data |
| POST | `/api/rail-tickets/{ticket_id}/annul` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/restore` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/calendar` | data.read | False | Read existing data/page without production changes |
| GET | `/api/employees/{employee_id}/luvr/calendar/day` | data.read | False | Read existing data/page without production changes |
| GET | `/api/luvr/month/export` | excel.export | False | Download existing report or in-memory export; no archive publication |
| POST | `/api/luvr/month/export` | excel.export | True | Download existing report or in-memory export; no archive publication |
| GET | `/api/luvr/month/settings` | data.read | False | Read existing data/page without production changes |
| PUT | `/api/luvr/month/settings` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/luvr/month/header-snapshot` | data.read | False | Read existing data/page without production changes |
| GET | `/api/luvr/month` | data.read | False | Read existing data/page without production changes |
| POST | `/api/luvr/month/form` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/luvr/month/employees` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| DELETE | `/api/luvr/month/employees/{employee_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/absences` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/absences` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/absences/{source}/{item_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/absences/{source}/{item_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/production-assignments` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/production-assignments` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/production-assignments/{change_id}` | data.update | True | Edit ordinary production/directory data |
| GET | `/api/employees/{employee_id}/production-matrix-overrides` | data.read | False | Read existing data/page without production changes |
| PATCH | `/api/employees/{employee_id}/production-matrix-overrides` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/production-matrix-overrides/{override_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/production-matrix` | data.read | False | Read existing data/page without production changes |
| GET | `/api/production-matrix/capabilities` | data.read | False | Read existing data/page without production changes |
| PUT | `/api/employees/{employee_id}/production-matrix/dk/{target}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| DELETE | `/api/employees/{employee_id}/production-matrix/dk/{target}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/deployment/analysis` | data.read | False | Read existing data/page without production changes |
| GET | `/api/deployment/report` | data.read | False | Read existing data/page without production changes |
| GET | `/api/deployment/report/export` | excel.export | False | Download existing report or in-memory export; no archive publication |
| PATCH | `/api/crew-memberships` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/objects/{item_id}/archive` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/objects/{item_id}/restore` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/objects/{item_id}/activity-status` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/subobjects/{item_id}/archive` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/subobjects/{item_id}/restore` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/subobjects/{item_id}/activity-status` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/construction-entities/environment` | data.read | False | Read existing data/page without production changes |
| GET | `/api/construction-entities` | data.read | False | Read existing data/page without production changes |
| PATCH | `/api/construction-entities/{entity_id}/hierarchy` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/vou/settings` | data.read | False | Read existing data/page without production changes |
| PUT | `/api/vou/settings` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/vou/reports` | data.read | False | Read existing data/page without production changes |
| GET | `/api/vou/reports/{report_id}` | data.read | False | Read existing data/page without production changes |
| GET | `/api/vou/reports/{report_id}/file` | excel.export | False | Download existing report or in-memory export; no archive publication |
| POST | `/api/vou/reports` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/clean-construction-entities/aliases` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/aliases` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/aliases/{alias_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| DELETE | `/api/clean-construction-entities/aliases/{alias_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/match` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report-match` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report/parse` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/word-report/dictionaries` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report/confirm` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/environment` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/workspace` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/word-report/workspace` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/categories` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/employees` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/po-types` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/employees/{employee_id}/assignments` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/employees/{employee_id}/assignments` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/employees/{employee_id}/assignments/{assignment_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| DELETE | `/api/clean-construction-entities/employees/{employee_id}/assignments/{assignment_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/{entity_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/{entity_id}` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/{entity_id}/hierarchy` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/{entity_id}/archive` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/{entity_id}/restore` | DENY | False | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| MOUNT | `/static` | data.read | False | Authenticated static assets only |
| GET | `/` | data.read | False | Read existing data/page without production changes |
| GET | `/api/select-folder` | DENY | False | Server filesystem access / GUI side effects; local operator only pending approval |
| GET | `/api/check-folder` | DENY | False | Server filesystem access / GUI side effects; local operator only pending approval |
| POST | `/api/process-folder` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/object-categories` | data.read | False | Read existing data/page without production changes |
| GET | `/api/po-types` | data.read | False | Read existing data/page without production changes |
| GET | `/api/objects` | data.read | False | Read existing data/page without production changes |
| POST | `/api/objects` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/objects/{object_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/objects/{object_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/object-categories/{parent_id}/children` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/object-categories/{category_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/object-categories/{category_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/po-types` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/po-types/{po_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/po-types/{po_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/positions` | data.read | False | Read existing data/page without production changes |
| POST | `/api/positions` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/positions/{position_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/positions/{position_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/employees/{employee_id}/archive` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/employees/{employee_id}/restore` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/assignments` | data.read | False | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/assignments` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/assignments/{assignment_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/assignments/{assignment_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/crews` | data.read | False | Read existing data/page without production changes |
| POST | `/api/crews` | data.create | True | Create ordinary production/directory data |
| PATCH | `/api/crews/{crew_id}` | data.update | True | Edit ordinary production/directory data |
| DELETE | `/api/crews/{crew_id}` | DENY | False | Separate authority required: workflow, deletion, processing, settings or bulk changes |

Total: 163
{'data.read': 48, 'PUBLIC': 1, 'SESSION': 2, 'DENY': 77, 'data.create': 15, 'data.update': 16, 'excel.export': 4}
