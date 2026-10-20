# Step 28: exact route authorization matrix

Date: 2026-10-18. Isolated entry only; app.main/live port 8001 unchanged.

Roles: ST = SYSTEM_TECHNICIAN; OM = OFFICE_MANAGER. Permissions come from server-side DB sessions. All unknown routes and changed handler identities are denied.

| Method | Route | Permission | ST | OM | Guard / actual action |
|---|---|---|---|---|---|
| GET | `/openapi.json` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| HEAD | `/openapi.json` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/docs` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| HEAD | `/docs` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/docs/oauth2-redirect` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| HEAD | `/docs/oauth2-redirect` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/redoc` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| HEAD | `/redoc` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/auth/login` | PUBLIC | PUBLIC login | PUBLIC login | Stage 2 login, same-origin and rate limited |
| GET | `/api/auth/me` | SESSION | Own session only | Own session only | Stage 2 own session; logout requires CSRF |
| POST | `/api/auth/logout` | SESSION | Own session only | Own session only | Stage 2 own session; logout requires CSRF |
| POST | `/api/daily-control-results/review-options` | data.create | ALLOW | DENY | daily.options; review_no_approval; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| GET | `/api/daily-control-results/absence-rules` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| DELETE | `/api/daily-control-results/absence-rules/{field}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/daily-control-results/review-category` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/daily-control-results/review-assignments/{employee_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/daily-control-results/check` | data.create | ALLOW | DENY | daily.check; daily_no_replace; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| POST | `/api/daily-control-results` | data.create | ALLOW | DENY | daily.save; daily_no_replace; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| GET | `/api/daily-control-results` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/daily-control-results/facts/{fact_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/daily-control-results/upload-day` | data.create | ALLOW | DENY | daily.upload; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| DELETE | `/api/daily-control-results/facts/{fact_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/daily-control-results/upload-file` | data.create | ALLOW | DENY | daily.upload; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| GET | `/api/subobjects` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/subobjects/{subobject_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/subobjects` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/subobjects/{subobject_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| GET | `/api/value-aliases` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/subobjects/{subobject_id}/move/check` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/subobjects/{subobject_id}/move` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/value-aliases/{alias_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/value-aliases` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/value-aliases/{alias_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/value-aliases/{alias_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/movements` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/movements` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/movements/{item_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/movements/{item_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/sick-periods` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/sick-periods` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/sick-periods/{item_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/sick-periods/{item_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/duration-exceptions` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/duration-exceptions` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/luvr/duration-exceptions/{item_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/duration-exceptions/{item_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/day-overrides` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/luvr/day-overrides` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/luvr/day-overrides/{item_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/upload` | data.create | ALLOW | DENY | tickets.upload; single_ticket_file; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| GET | `/api/rail-tickets` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/rail-tickets/{ticket_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PATCH | `/api/rail-tickets/{ticket_id}/direction` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/confirm` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/reject` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/rail-tickets/{ticket_id}/object` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| POST | `/api/rail-tickets/{ticket_id}/annul` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/rail-tickets/{ticket_id}/restore` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/luvr/calendar` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/employees/{employee_id}/luvr/calendar/day` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/luvr/month/export` | excel.export | ALLOW | ALLOW | Download existing report or in-memory export; no archive publication |
| POST | `/api/luvr/month/export` | excel.export | ALLOW | ALLOW | Download existing report or in-memory export; no archive publication |
| GET | `/api/luvr/month/settings` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PUT | `/api/luvr/month/settings` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/luvr/month/header-snapshot` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/luvr/month` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/luvr/month/form` | data.create | ALLOW | DENY | luvr.form; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| POST | `/api/luvr/month/employees` | data.create | ALLOW | DENY | luvr.member; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| DELETE | `/api/luvr/month/employees/{employee_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/absences` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/absences` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/absences/{source}/{item_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/absences/{source}/{item_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/production-assignments` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/production-assignments` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/production-assignments/{change_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| GET | `/api/employees/{employee_id}/production-matrix-overrides` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PATCH | `/api/employees/{employee_id}/production-matrix-overrides` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/production-matrix-overrides/{override_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/production-matrix` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/production-matrix/capabilities` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PUT | `/api/employees/{employee_id}/production-matrix/dk/{target}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| DELETE | `/api/employees/{employee_id}/production-matrix/dk/{target}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/deployment/analysis` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/deployment/report` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/deployment/report/export` | excel.export | ALLOW | ALLOW | Download existing report or in-memory export; no archive publication |
| PATCH | `/api/crew-memberships` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/objects/{item_id}/archive` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/objects/{item_id}/restore` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/objects/{item_id}/activity-status` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/subobjects/{item_id}/archive` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/subobjects/{item_id}/restore` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| PATCH | `/api/subobjects/{item_id}/activity-status` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/construction-entities/environment` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/construction-entities` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PATCH | `/api/construction-entities/{entity_id}/hierarchy` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/vou/settings` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| PUT | `/api/vou/settings` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/vou/reports` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/vou/reports/{report_id}` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/vou/reports/{report_id}/file` | excel.export | ALLOW | ALLOW | Download existing report or in-memory export; no archive publication |
| POST | `/api/vou/reports` | data.create | ALLOW | DENY | vou.generate_archive; Step28 explicit workflow approval; guarded against deletion/approval/bulk branches |
| GET | `/api/clean-construction-entities/aliases` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/aliases` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/aliases/{alias_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| DELETE | `/api/clean-construction-entities/aliases/{alias_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/match` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report-match` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report/parse` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/word-report/dictionaries` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/word-report/confirm` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/environment` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/workspace` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/word-report/workspace` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/categories` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/employees` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/po-types` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/employees/{employee_id}/assignments` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/employees/{employee_id}/assignments` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/employees/{employee_id}/assignments/{assignment_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| DELETE | `/api/clean-construction-entities/employees/{employee_id}/assignments/{assignment_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| GET | `/api/clean-construction-entities/{entity_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/{entity_id}` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| PATCH | `/api/clean-construction-entities/{entity_id}/hierarchy` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/{entity_id}/archive` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| POST | `/api/clean-construction-entities/{entity_id}/restore` | DENY | DENY | DENY | Separate CLEAN_START database/public schema; outside approved 8001 target, including read routes |
| MOUNT | `/static` | data.read | ALLOW | ALLOW | Authenticated static assets only |
| GET | `/` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/select-folder` | DENY | DENY | DENY | Server filesystem access / GUI side effects; local operator only pending approval |
| GET | `/api/check-folder` | DENY | DENY | DENY | Server filesystem access / GUI side effects; local operator only pending approval |
| POST | `/api/process-folder` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/object-categories` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/po-types` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| GET | `/api/objects` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/objects` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/objects/{object_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/objects/{object_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/object-categories/{parent_id}/children` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/object-categories/{category_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/object-categories/{category_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/po-types` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/po-types/{po_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/po-types/{po_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/positions` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/positions` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/positions/{position_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/positions/{position_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/employees/{employee_id}/archive` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| POST | `/api/employees/{employee_id}/restore` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/employees/{employee_id}/assignments` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/employees/{employee_id}/assignments` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/employees/{employee_id}/assignments/{assignment_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/employees/{employee_id}/assignments/{assignment_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
| GET | `/api/crews` | data.read | ALLOW | ALLOW | Read existing data/page without production changes |
| POST | `/api/crews` | data.create | ALLOW | DENY | Create ordinary production/directory data |
| PATCH | `/api/crews/{crew_id}` | data.update | ALLOW | DENY | Edit ordinary production/directory data |
| DELETE | `/api/crews/{crew_id}` | DENY | DENY | DENY | Separate authority required: workflow, deletion, processing, settings or bulk changes |
