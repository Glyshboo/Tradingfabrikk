@echo off
setlocal
cd /d "%~dp0.."

set "REPO_ROOT=%CD%"
set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

start "paper" cmd /k "cd /d ^"%REPO_ROOT%^" && ^"%PYTHON_EXE%^" -m apps.paper_runner --config configs/active.yaml || (echo. && echo [ERROR] paper launcher failed during startup. && pause)"
start "research" cmd /k "cd /d ^"%REPO_ROOT%^" && ^"%PYTHON_EXE%^" -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml || (echo. && echo [ERROR] research launcher failed during startup. && pause)"
