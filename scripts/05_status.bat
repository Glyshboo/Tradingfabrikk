@echo off
setlocal
cd /d "%~dp0.."

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

title status
"%PYTHON_EXE%" -m apps.status_tool --status-file runtime/status.json
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] status launcher failed with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
