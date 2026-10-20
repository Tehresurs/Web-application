# Step 26 ? PostgreSQL-level authorization test isolation, 18.10.2026

Project 8001 only. Existing service remained on 127.0.0.1:8001, PID 728.
No 8000 start, mandatory authorization, Tunnel, application/API/UI changes,
production migrations, role/grant changes or shared PostgreSQL configuration changes.

## Isolation

Reused and verified existing independent PostgreSQL 18 cluster runner under
backend/output/security/auth_isolated/<UTC+UUID>. Each run owns a separate data
directory, random loopback port, temporary administrator and restricted worker role.
Existing cluster receives only read-only SELECT snapshots and negative login tests.
Worker receives no source-superuser credentials. Source role name checked absent.
Application tests connect only as the restricted temporary role. Supervisor alone
uses administrator privileges inside its OWN cluster for setup/restoration/cleanup.
The source connection may use the existing configured privileged account but only
inside explicit read-only transactions; it is not passed into application tests.

Worker role has LOGIN, no SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS.
Inside copies: schema USAGE, SELECT/INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES and
sequence USAGE/SELECT/UPDATE. Only migration suite additionally gets schema CREATE.
No grants or role created in shared cluster. No ownership of source objects.
Native PostgreSQL permissions, not monkey-patches, enforce rejection.
Repository factory substitutions still select test datasets but are not the barrier.

## Scenarios and results

- 27 integration tests PASS (8 structure, 11 session, 8 route policy).
- 5 infrastructure tests PASS: setup cleanup, first-stop failure retry, preserve
  directory if still running, reject outside path, unique report directories.
- Correct copied-DB access and necessary DML succeed as restricted role.
- Actual source DB rejects direct, saved-alias and wrong-environment login using
  isolated credentials. PostgreSQL authentication error positively classified.
- Local decoy named ai_excel_agent_test has same schema/table names with no grants;
  UPDATE denied by PostgreSQL for direct/saved-alias/bad-DB_NAME scenarios.
- Decoy sentinel remains unchanged. Backup SHA256, restore exit status and original
  table row counts checked. Read/export tests preserve copied table contents.
- Final working DB snapshots: ALL 41 tables identical, canonical UTC/ISO/C ordering.
- Clusters stopped and data directories removed; temporary roles/databases removed
  with them. No cleanup errors and no remaining test-cluster directories.

## Infrastructure diagnostic changes in this step

scripts/auth_test_worker.py now tests three actual source-login paths and checks
server authentication rejection, not arbitrary OperationalError/network timeout.
libpq on this host returns missing SQLSTATE and locale-encoded error bytes. Raw
message is classified in UTF-8/CP1251 without saving credentials or raw errors.
This avoids falsely treating a network failure as proof of authorization denial.
scripts/run_auth_isolated.py retains worker.stderr.log with generated passwords
redacted if worker fails before producing its JSON result. No application changes.
Each run retains report.json, tests.txt, PostgreSQL/tools logs; infrastructure checks
saved in infrastructure-tests.txt in the final run. Previous runs not overwritten.

## IMPORTANT: first-run source difference

First run failed before authorization test suite startup because requiring SQLSTATE
alone did not recognize the localized libpq authentication error. Cluster removed.
Source before/after fingerprints differed for daily_control_results and
report_review_events. No rows were restored, edited or normalized by this task.
Cause/actor not established. Do not claim the entire step had no source changes.
The restricted worker did not reach the integration suites in that run.
construction_objects did NOT differ in either run; its historical discrepancy
remains OPEN with unknown cause. Final successful run had zero changed tables.

## Readiness and limits

Ready for further isolated authorization testing. Not authorization deployment.
The guarantee applies to tests using the supplied restricted credentials. A malicious
Windows process able to read project secrets is outside this isolation boundary.
The supervisor has source read access; worker is deliberately not given its secret.
Concurrent normal app usage can change source fingerprints and cannot be attributed
by the hash alone. A maintenance window is required for an interval-wide invariance
claim; no lock or freeze of production app was introduced.
Migration tests adapt the DB-name guard only inside disposable copies. No migration
applied to source. Backups contain personnel data; diagnostics directory ACL is
restricted to current Windows account. Do not publish it.

First attempt: backend/output/security/auth_isolated/20261018T180823Z_c93171a831bb43c5a2060b552220f804
Final attempt: backend/output/security/auth_isolated/20261018T181353Z_3ed9df5bf2d64b2c980306e0b095be4e
Restricted role (only in removed cluster): iso_test_6a1ddcd2133a4dd782042ab861c8d99f
Temporary copied databases: auth_stage1_restore_f3930aca0b9e4f279a84307efa6244ae, auth_stage2_1bec5170422a4e37be98a74ca791dcff, auth_stage3_12aa227e0546484292933edf088f6517
Local decoy ai_excel_agent_test was also only inside removed isolated cluster.

Run with project interpreter:
C:/Projects/excel-ai-agent-8001/backend.venv/Scripts/python.exe -B backend/scripts/run_auth_isolated.py

No next stage performed.
