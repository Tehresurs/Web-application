# Step 23: 8001 independent runtime switch ? 18.10.2026

Successful switch of ONLY 8001. No application code, API, authentication policy,
migrations, production DB/schema/roles, 8000 or PostgreSQL service changed.

Before: listener PID 17864, virtual-environment launcher parent PID 5524.
Command: C:/Projects/excel-ai-agent/backend/.venv/Scripts/python.exe C:/Projects/run_report_review_8001.py.
After: listener PID 728, virtual-environment launcher parent PID 13544;
launching hidden PowerShell PID 10624.
Command: C:/Projects/excel-ai-agent-8001/backend.venv/Scripts/python.exe -B C:/Projects/run_report_review_8001.py.
Started through start_8001_independent.ps1 -Start, exactly as authorized.

Preflight: actual interpreter and script paths matched. Launcher probe passed with
HTTP startup intercepted and read-only DB connection. No established HTTP sessions,
active DB sessions or handler children. VOU files had not changed for over 25 minutes.
Rollback script and before snapshot saved before shutdown.
CTRL_C did not stop old process. Uvicorn supports SIGBREAK on Windows; targeted
CTRL_BREAK to the verified dedicated 8001 console completed shutdown. No broad
Python termination or forced process kill. New server bound only after old port freed.

Checks: root, employees, objects, tickets, October 2026 LUVR and production matrix,
VOU report list and existing XLSM download all HTTP 200. Database environment
API confirms ai_excel_agent_test / test_construction_identity_stage46.
Existing XLSM SHA256: 9968b87a59b2636bc91c115306511e0b16534e05144ca217d0defeee41b239c8.
No report generation/publication or export generation invoked.
All 41 working-schema table counts and canonical row hashes match before/after.
Native pydantic, lxml and psycopg modules loaded from backend.venv; none found under
old project .venv in process module inventory. Venv still uses the installed base
Python 3.13 interpreter as expected, not its old virtual environment packages.

Excel COM 16.0: new owned empty instance PID 10324, macros disabled, zero workbooks
opened, Quit and COM release. Existing Excel instances not closed.
Root and data endpoints remain available without new mandatory login. Matrix
capabilities remain LEADER/single_user as before. Current on-disk app includes
previously prepared optional auth routes; no global auth factory installed.

8000 listener remains PID 1064. Existing PostgreSQL service not restarted.
No Windows autostart/service changes. No Cloudflare Tunnel or external publication.

Evidence directory: backend/output/switch_8001/20261018T165206Z_84ce67d9/.
state.json, before.json, after.json, checks.json, new.stdout.log, new.stderr.log.
rollback.ps1 restores OLD interpreter + SAME launcher only if 8001 is free;
not invoked. Do not run it while current 8001 occupies the port. Retain old files
for rollback; deleting 8000 project is a separately authorized task.
All requested checks passed; no next step taken.
