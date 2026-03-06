@echo off
setlocal
cd /d "%~dp0.."

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

REM Unified review launcher (legacy name kept for compatibility)
"%PYTHON_EXE%" -m apps.review_server --host 127.0.0.1 --port 8787
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] review launcher failed with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
