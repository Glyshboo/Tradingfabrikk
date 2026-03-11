@echo off
setlocal
cd /d "%~dp0.."

title paper
call scripts\_bootstrap_python_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Klarte ikke klargjore Python-miljo for paper-runner.
    pause
    exit /b 1
)

if not defined REPO_PYTHON (
    echo [ERROR] Bootstrap fullforte ikke korrekt ^(REPO_PYTHON mangler^).
    pause
    exit /b 1
)

"%REPO_PYTHON%" -m apps.paper_runner --config configs/active.yaml
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] paper launcher feilet med exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
