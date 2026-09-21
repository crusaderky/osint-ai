@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
set "result=%ERRORLEVEL%"
echo.
pause
exit /b %result%
