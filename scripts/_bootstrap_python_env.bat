@echo off
setlocal
cd /d "%~dp0.."

set "REPO_ROOT=%CD%"
set "REQ_FILE=%REPO_ROOT%\requirements.txt"
set "VENV_DIR=%REPO_ROOT%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%REQ_FILE%" (
    echo [ERROR] Fant ikke requirements.txt i repo root: %REQ_FILE%
    exit /b 2
)

if exist "%VENV_PY%" goto HAVE_VENV

set "BOOTSTRAP_PY="
where py >nul 2>&1 && set "BOOTSTRAP_PY=py -3"
if not defined BOOTSTRAP_PY where python >nul 2>&1 && set "BOOTSTRAP_PY=python"

if not defined BOOTSTRAP_PY (
    echo [ERROR] Python ble ikke funnet i PATH.
    echo Installer Python 3.10+ fra https://www.python.org/downloads/ og huk av "Add python.exe to PATH".
    exit /b 3
)

echo [BOOTSTRAP] Oppretter lokal virtualenv i .venv ...
call %BOOTSTRAP_PY% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Klarte ikke opprette .venv.
    exit /b 4
)

:HAVE_VENV
echo [BOOTSTRAP] Oppdaterer pip/setuptools/wheel ...
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >nul
if errorlevel 1 (
    echo [ERROR] Klarte ikke oppgradere pip i .venv.
    exit /b 5
)

echo [BOOTSTRAP] Verifiserer/installere Python-avhengigheter ...
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%REQ_FILE%"
if errorlevel 1 (
    echo [ERROR] Dependency-installasjon feilet. Sjekk nettverk/proxy og prov igjen.
    exit /b 6
)

"%VENV_PY%" -c "import yaml, websockets" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Miljoet mangler fortsatt nodvendige pakker ^(PyYAML/websockets^).
    echo Kjor manuelt: "%VENV_PY%" -m pip install -r requirements.txt
    exit /b 7
)

endlocal & set "REPO_PYTHON=%VENV_PY%"
exit /b 0
