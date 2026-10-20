@echo off
setlocal
set "DEMO_PYTHON=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%DEMO_PYTHON%" set "DEMO_PYTHON=C:\Projects\excel-ai-agent\backend\.venv\Scripts\python.exe"
if not exist "%DEMO_PYTHON%" (
  echo Python environment not found.
  pause
  exit /b 1
)
pushd "%~dp0"
"%DEMO_PYTHON%" -B "%~dp0run_demo_viewer_8001.py"
set "DEMO_EXIT=%ERRORLEVEL%"
popd
if not "%DEMO_EXIT%"=="0" pause
exit /b %DEMO_EXIT%
