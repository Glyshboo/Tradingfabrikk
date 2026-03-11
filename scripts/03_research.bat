@echo off
setlocal
cd /d "%~dp0.."

title research
call scripts\_bootstrap_python_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Klarte ikke klargjore Python-miljo for research-runner.
    pause
    exit /b 1
)

"%REPO_PYTHON%" -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] research launcher feilet med exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
