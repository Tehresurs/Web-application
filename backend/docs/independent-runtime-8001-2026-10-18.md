# Independent Python runtime for 8001 ? 18.10.2026

## Scope

Prepared only C:/Projects/excel-ai-agent-8001. Existing servers not stopped/restarted.
No production logic/API/UI/authentication/migrations/database structure/configuration
changes. No old project BAT modified or executed. No Tunnel.

## Runtime

Interpreter: C:/Projects/excel-ai-agent-8001/backend.venv/Scripts/python.exe.
Python 3.13.6; base installation remains the existing system Python under the current
Windows user. No --system-site-packages. No old project paths in sys.path.
29 dependencies pinned in backend/requirements-8001.lock.txt, matching existing
runtime versions plus isolated-stage Argon2 dependencies. pip itself is 25.2.
Main packages: FastAPI 0.141.1, Uvicorn 0.53.0, Starlette 1.6.0,
psycopg/psycopg-binary 3.3.6, Pydantic 2.13.5, Jinja2 3.1.6,
python-docx 1.2.0, lxml 6.1.3, pypdf 6.19.0, openpyxl 3.1.5,
python-dotenv 1.2.3, python-multipart 0.0.32, argon2-cffi 25.1.0.
Exact transitive versions in lock file and installed-packages.json.
No installations or updates performed in the old virtual environment.

## Checks

- pip check: no broken requirements.
- AST inventory of non-stdlib application imports covered by installed packages.
- Imports of FastAPI/Uvicorn/Jinja2/docx/psycopg/dotenv/pypdf/multipart/openpyxl/argon2/lxml successful.
- Existing launcher executed with uvicorn.run intercepted: NO HTTP server launched.
- Existing read_only_request context forces PostgreSQL read-only connections during probe.
- Actual database ai_excel_agent_test; schema test_construction_identity_stage46;
  transaction_read_only=on; expected bind 127.0.0.1:8001.
- Argon2 hashes/verifies an in-memory test string without creating any account/session.
- Original VOU template SHA256 unchanged and matches expected master digest.
- Excel COM uses PowerShell, not pywin32. Excel 16.0 instantiated as a new owned
  process, macros disabled, zero workbooks opened. Only this owned empty instance
  received Quit; COM reference released. No pre-existing Excel process closed.
- Existing 8000 listener PID 1064 and 8001 PID 17864 unchanged.
- No temporary HTTP process or additional HTTP port needed.

## Safe launcher

New root script start_8001_independent.ps1 uses exact independent interpreter and
C:/Projects/run_report_review_8001.py. Default is CHECK ONLY. With -Start, performs
probe first, then refuses if 8001 is occupied; never stops/replaces any process.
Existing launcher explicitly sets APP_DB_PROFILE=test and overrides stale DB/schema
from dotenv before checking actual connection. Do not replace this with generic
uvicorn app.main:app, which can select wrong dotenv defaults.

Check only:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Projects/excel-ai-agent-8001/start_8001_independent.ps1

## Later switch ? NOT executed or authorized here

1. Agree a switch window and record existing process/launcher and a rollback command.
2. Re-run the check-only command and verify no current work is in progress.
3. After separate authorization, stop ONLY the verified 8001 launch tree; leave 8000
   and the shared PostgreSQL service running.
4. Start:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Projects/excel-ai-agent-8001/start_8001_independent.ps1 -Start
5. Verify process interpreter/parent points to backend.venv, actual DB/schema, loopback
   bind, pages, employees, tickets, matrix, LUVR and existing report downloads.
6. If unsuccessful, stop only the newly launched 8001 tree and restart the existing
   C:/Projects/run_report_review_8001.py with the preserved OLD interpreter. No DB
   restore is necessary for an interpreter-only switch if no writes occurred.

## Limits

The running 8001 has NOT switched; old project cannot yet be deleted.
Base Python, installed Microsoft Excel, PowerShell and PostgreSQL remain external
platform dependencies. Full native XLSM generation was not repeated and no official
report was generated. Native COM availability was verified separately.
The new launch uses current on-disk app code, including prepared auth routes; this
preparation does not activate mandatory authentication or change role policies.
No actual HTTP serve/start/stop cycle was performed. First real launch is a separately
authorized deployment check. Snapshot/hash checks of every production table were not
performed in this task: DB operations were SELECT-only under read-only connections.
The source requirements file retains its existing version policy; the separate lock
records this prepared Windows/Python environment, not a cross-platform lock.

Files: backend.venv/ (ignored), backend/requirements-8001.lock.txt,
start_8001_independent.ps1, backend/scripts/check_independent_runtime.py,
backend/scripts/check_excel_com_independent.ps1, .gitignore (exclude backend.venv),
this document and verification artifacts under backend/output/runtime_preparation/.
