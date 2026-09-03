@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHONW=%APP_ROOT%.venv\Scripts\pythonw.exe"

if not exist "%PYTHONW%" goto missing_python

start "" /D "%APP_ROOT%" "%PYTHONW%" -m ytdownloader
exit /b 0

:missing_python
echo Python environment was not found. Run the setup steps in README.md first.
pause
exit /b 1
