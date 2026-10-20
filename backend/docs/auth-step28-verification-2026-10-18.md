# Step 28: isolated authorization policies verification

Scope: C:/Projects/excel-ai-agent-8001 only. Source: ai_excel_agent_test/test_construction_identity_stage46. No live authorization activation, restart, migrations or account creation.

## Changes

Changed app/auth_route_policies.json, app/auth_policies.py, app/auth_protected.py, tests/test_auth_policies.py. Added this report and auth-step28-route-matrix-2026-10-18.md (all 163 method/path/handler policies).

Nine previously denied workflow routes now require data.create, the database-derived SYSTEM_TECHNICIAN role and CSRF: daily upload-day/upload-file/check/save/review-options, single rail-ticket upload, LUVR month form/single-member insertion, VOU generation/archive. Existing read/export/create/update permissions remain; no production grants changed. Unknown routes remain denied. Password/session/rate-limit implementation unchanged.

Payload guards reject daily fact replacement (DELETE of old facts/overrides), approval/rule changes in review-options, and multiple ticket files. Request bodies are replayed to the actual handler after validation; maximum guarded body is 11 MiB. Manager cannot invoke these workflows. Client-supplied role or employee ID does not establish authority.

## Verification

Final isolated run: 20261018T183317Z_79a7a927c54e486898ce505e3e208574.
8 structure + 11 login/session/CSRF + 14 policy tests = 33 successful integration tests.
All source schema table counts and canonical fingerprints before/after match (41 tables). Test worker uses restricted credentials in its own temporary PostgreSQL cluster; source-account credentials are absent from worker. Native direct/saved connection and wrong-database denial checks run independently of Python monkeypatch. Cluster removed; no cleanup errors.

Policy tests cover anonymous denial, complete registry and handler identity, both-role reads and Excel exports, engineer actual create/edit and LUVR formation in clone DB, manager mutation denial, all explicit denied routes, unknown/user-management routes, spoofed role/employee, CSRF, mixed workflow rejection, single upload handling, and VOU publication/download.

Uploads use parser stand-ins and temporary storage. VOU test mocks B2 preparation and Excel rendering, then exercises actual route orchestration and VouArchive with a synthetic XLSM ZIP in a temporary directory. Two publications have different UUIDs; manager can download but cannot generate. DB fingerprints unchanged by publication. This is NOT a native Excel COM, VBA preservation, print-layout or real-report content test. Existing COM validation is not weakened. No official report published.

Actual VOU generation reads saved requisites and B2, creates new output XLSM/PDF/audit files, and publishes new UUID report.xlsm/snapshot.json using staging plus atomic rename. It does not update production tables or overwrite prior archive reports. Failure cleanup is limited to newly created unpublished staging files. LUVR formation inserts month/employee report snapshots; source employees are not rewritten.

First run had two failing tests caused by missing receive stream in the isolated payload-check wrapper. Fixed and all tests repeated successfully. Its report is preserved at 20261018T182944Z_abc23a2872b945bfab4e8f22d98ae710; source fingerprints also unchanged.

## Conflicts requiring separate agreement

- Replacing saved daily facts requires deletion of old facts/overrides: blocked even for engineer. New fact saving remains permitted.
- Daily review approval and persistent recognition rules: blocked.
- Ticket confirmation creates movement and changes confirmation state; annulment may delete movement: blocked. Single upload and permitted ordinary movement routes do not grant confirmation/annulment.
- Multiple ticket upload, folder processing/selection, crew bulk operations and other mass/irreversible routes remain blocked.
- All 26 clean-construction-entities routes remain blocked: alternate connection/schema settings require separate isolation and authorization agreement. Thus access to these alternative views is an explicit exception to general all-sections viewing.
- Deletion, user/role administration, system settings, archive/restore of production entities, and other previously denied operations remain blocked. New VOU report publication is the narrowly approved archive operation.

Readiness: policies are ready for the next separately authorized integration stage, subject to the above workflow limitations. Live activation is NOT performed. Live 8001 listener PID remains 728. No 8000 or Tunnel startup. Historical construction_objects fingerprint discrepancy remains open with unknown cause; no repair attempted.

Policy counts: {'data.read': 48, 'PUBLIC': 1, 'SESSION': 2, 'data.create': 24, 'DENY': 68, 'data.update': 16, 'excel.export': 4}.
Diagnostic report: backend/output/security/auth_isolated/20261018T183317Z_79a7a927c54e486898ce505e3e208574/report.json
