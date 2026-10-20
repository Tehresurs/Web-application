# Safe authorization test isolation ? 18.10.2026

Scope: project 8001 only. Source: ai_excel_agent_test / test_construction_identity_stage46.
Existing PostgreSQL cluster, roles, grants, configuration, server 8000 and production app unchanged.

## Design

run_auth_isolated.py starts a NEW temporary PostgreSQL 18 cluster on a randomly allocated loopback port.
Data directory is inside backend/output/security/auth_isolated/<UTC+UUID>/cluster.
SCRAM authentication. Separate temporary cluster administrator iso_admin_<uuid> is used ONLY by supervisor.
Worker receives only iso_test_<uuid> LOGIN credentials, without SUPERUSER, CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS.
No memberships or grants in the existing cluster. Source DB is accessed only for read-only fingerprints and negative login proof.
Worker environment is rebuilt from an OS-variable allowlist. Source credentials are not passed. dotenv loading is disabled before application imports.
No connection monkey-patch is needed to enforce PostgreSQL permission denial; factory substitutions only route repositories into test copies.

Three temporary databases: stage1 restored source schema; stage2 minimal employees/auth fixture; stage3 restored source schema plus auth migration.
A fourth local decoy is named ai_excel_agent_test, with protected schema/table and no worker grants.
Worker can perform DML, TRUNCATE, REFERENCES, sequence operations only on test objects; stage1 additionally needs schema CREATE to test migration rollback.
It is not an owner of the other test tables/sequences and cannot create databases or roles.
Old direct test entrypoints fail closed; old privileged setup/cleanup fixtures removed. check_auth_stage2.py and check_auth_stage3.py redirect to new runner.

## Verified

27 integration checks passed: 8 structure, 11 session/password, 8 policy tests.
Native PostgreSQL tests: source connection using unique isolated role rejected; decoy SQL UPDATE denied with InsufficientPrivilege via direct psycopg, saved connection alias, and wrong DB_NAME environment.
Role flags checked on actual server; normal test DML succeeds only inside isolated databases.
The source role name was checked absent before starting the worker.
Restored backup SHA256 verified, pg_restore uses exit-on-error, row counts for all 34 original tables checked.
Stage3 tests also compare restored-table contents before/after viewing/exporting; decoy row remains unchanged.
5 offline infrastructure tests passed: preparation failure cleanup, retry after first stop error, preserve live cluster after failed cleanup, reject outside path, unique non-overwriting report directories.
Cleanup checks pg_ctl status, retries stop, and NEVER deletes a directory while cluster is still running.
Owned path containment checked before recursive removal. Process exits or power failures can still leave an owned directory: inspect its report rather than deleting blindly.
Temporary roles/databases are removed with the entire stopped cluster data directory.
Current working schema: all 41 table counts and canonical row fingerprints match before/after final successful runs.

## Diagnostics and failed attempts

Each run creates a new UTC+UUID directory; reports never overwrite previous attempts. ACL restricted to current Windows account.
Initial snapshot saved before starting cluster; final report retained on failure; passwords not written into report.
Canonical source snapshots use UTC, ISO dates and C sort collation; these hashes are a NEW baseline, not directly comparable to historical locale-dependent fingerprints.
First run hit Windows inherited-pipe waiting during pg_ctl startup. Only owned temporary cluster was stopped; directory removed; source unchanged. Tool output now goes to files, with timeouts.
Second run exposed insufficient ownership for TRUNCATE RESTART IDENTITY and a fixture signature mismatch. Ownership was NOT granted; restart-identity removed from test reset and adapter fixed.
Both failures remain in their own directories. Subsequent two runs passed and removed clusters.

## Files

- scripts/run_auth_isolated.py ? supervisor, source snapshots, cluster provisioning and reports.
- scripts/auth_test_worker.py ? restricted worker and fixture lifecycle adapters.
- scripts/auth_cluster_cleanup.py ? bounded owned-directory cleanup.
- tests/test_auth_isolation_infrastructure.py ? failure/cleanup tests.
- tests/test_auth_structure.py, test_user_auth.py, test_auth_policies.py ? legacy fixture entrypoints disabled; business assertions preserved.
- scripts/check_auth_stage2.py, check_auth_stage3.py ? safe legacy aliases.
- this document.

## Remaining limits

This protects against accidental connections under restricted test credentials, not malicious code running as the Windows account that can read project secret files.
Supervisor still needs existing administrative credentials ONLY to read the source and owns credentials for its independent cluster; worker never receives them.
Negative source login proof currently accepts OperationalError; it does not persist a SQLSTATE classification. Source connectivity is separately verified by successful before/after snapshots and role absence is checked.
Source fingerprints can detect concurrent legitimate changes but cannot attribute authorship. construction_objects historic discrepancy remains OPEN with unknown cause; not corrected.
Backup is a verified stage1 snapshot; it is not claimed to represent current live data.
Test directories/backup contain personnel data and must not be published. Logs are local and ACL restricted.
No activation of production authentication, real accounts, UI, roles/permissions, Tunnel or next stage.

## Run history

### 20261018T160753Z_7859308bda484d4792357810e62c46b9

- Report: backend/output/security/auth_isolated/20261018T160753Z_7859308bda484d4792357810e62c46b9/report.json
- Success: False; source unchanged: True; cluster removed: True

### 20261018T161458Z_71f8d6bd2b494cb3a105ac39578d7cf6

- Report: backend/output/security/auth_isolated/20261018T161458Z_71f8d6bd2b494cb3a105ac39578d7cf6/report.json
- Success: False; source unchanged: True; cluster removed: True
- Isolated test role: `iso_test_841148a507e94414bfee21c0c402bfab`
- Temporary DB names: `auth_stage1_restore_8fe019e8b40241279136ca60d5ad5371`, `auth_stage2_0e6b430b51094fd285ad8bf6f44da97a`, `auth_stage3_a12f7256de564999825e962cb9d57cc3`; local decoy `ai_excel_agent_test`.

### 20261018T161720Z_dcb82ac23523447cbb4b43ad96047dc7

- Report: backend/output/security/auth_isolated/20261018T161720Z_dcb82ac23523447cbb4b43ad96047dc7/report.json
- Success: True; source unchanged: True; cluster removed: True
- Isolated test role: `iso_test_711582b0a41041ca8c8dfee001f16b94`
- Temporary DB names: `auth_stage1_restore_182c817f02714b19b4a5d3fb5e0ae7a1`, `auth_stage2_4f43c17efeb04c178af6a97bb08e6252`, `auth_stage3_1a3b9402301a4d40bf7f0b2aa616d4c7`; local decoy `ai_excel_agent_test`.

### 20261018T161944Z_0ccf23a5e76e4202b5569edb8132a0ff

- Report: backend/output/security/auth_isolated/20261018T161944Z_0ccf23a5e76e4202b5569edb8132a0ff/report.json
- Success: True; source unchanged: True; cluster removed: True
- Isolated test role: `iso_test_47862f86c9b94ec1acbd79acc049cfa4`
- Temporary DB names: `auth_stage1_restore_27ef01ec8a214f46809bdd5820d776ba`, `auth_stage2_7950a6c1cc624beb86b4424e6915753f`, `auth_stage3_d56a26167baf405280595d10cae25426`; local decoy `ai_excel_agent_test`.
