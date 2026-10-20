@echo off
setlocal
title Tehresurs 8001
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open_tehresurs_8001.ps1" %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" exit /b 0
echo.
echo Tehresurs 8001 could not be opened. See the message above.
pause
exit /b %RESULT%
