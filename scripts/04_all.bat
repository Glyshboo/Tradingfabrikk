@echo off
setlocal
cd /d "%~dp0.."

set "REPO_ROOT=%CD%"
start "paper" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\02_paper.bat"
start "research" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\03_research.bat"
