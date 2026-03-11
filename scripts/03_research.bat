@echo off
setlocal
cd /d "%~dp0.."

title Lord Heibo Research Batch

call scripts\_bootstrap_python_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Klarte ikke klargjore Python-miljo for research-runner.
    pause
    exit /b 1
)

if not defined REPO_PYTHON (
    echo [ERROR] Bootstrap fullforte ikke korrekt ^(REPO_PYTHON mangler^).
    pause
    exit /b 1
)

echo ======================================================================
echo [LORD HEIBO LAB] Research batch starter

echo - Kjorer EN research-pass, skriver artifacts, og avslutter
echo - Dette er forventet oppforsel for batch-jobb
echo ======================================================================

echo.
"%REPO_PYTHON%" -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Research batch feilet med exit code %EXIT_CODE%.
    echo Sjekk output over. runtime\research_last_run.json oppdateres med feildata.
    pause
    exit /b %EXIT_CODE%
)

echo [OK] Research batch fullfort.
echo Se runtime\research_last_run.json for siste run-info.
echo Se runtime\review_artifacts\ for kandidat-artifacts.
echo Se scripts\05_status.bat for operatoroversikt.
echo.
echo Merk: Research er batch-basert og avslutter etter ett pass med vilje.
pause
exit /b 0
