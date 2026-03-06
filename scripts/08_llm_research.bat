@echo off
setlocal
cd /d "%~dp0.."

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

"%PYTHON_EXE%" -m apps.llm_research_runner --config configs/active.yaml
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] llm_research launcher failed with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
