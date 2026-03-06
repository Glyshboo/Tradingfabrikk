@echo off
setlocal
cd /d "%~dp0.."

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

"%PYTHON_EXE%" -m apps.strategy_ideas_status --ideas-dir strategy_ideas
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] strategy_ideas_status launcher failed with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
