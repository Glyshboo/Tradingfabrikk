@echo off
setlocal
cd /d "%~dp0.."

title Lord Heibo Operator Status
call scripts\_bootstrap_python_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Klarte ikke klargjore Python-miljo for status-tool.
    pause
    exit /b 1
)

if not defined REPO_PYTHON (
    echo [ERROR] Bootstrap fullforte ikke korrekt ^(REPO_PYTHON mangler^).
    pause
    exit /b 1
)

echo.
echo [LORD HEIBO OPERATOR] Starter status monitor...
echo - Trykk Ctrl+C for aa stoppe watch-mode.
echo.
"%REPO_PYTHON%" -m apps.status_tool --status-file runtime/status.json --watch --interval 5
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] status launcher feilet med exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
