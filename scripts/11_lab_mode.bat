@echo off
setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0.."
set "REPO_ROOT=%CD%"

title Lord Heibo Tradingfabrikk Lab

:menu
cls
echo ======================================================================
echo   👑 Lord Heibo Tradingfabrikk Lab ^(paper-first operator mode^)
echo ======================================================================
echo   1^) Start full lab mode ^(paper + status monitor + review UI^)
echo   2^) Start kun paper engine

echo   3^) Kjor en research-pass ^(batch^)
echo   4^) Apne operator dashboard/status monitor

echo   5^) Apne review monitor ^(web UI^)
echo   6^) Apne LLM exports mappe

echo   7^) Apne paste_to_llm.md

echo   8^) Live mode info ^(separat, eksplisitt og bevisst^)
echo   9^) Avslutt

echo ======================================================================
set /p CHOICE=Velg handling [1-9]: 

if "%CHOICE%"=="1" goto full_lab
if "%CHOICE%"=="2" goto paper_only
if "%CHOICE%"=="3" goto research_once
if "%CHOICE%"=="4" goto status
if "%CHOICE%"=="5" goto review
if "%CHOICE%"=="6" goto exports
if "%CHOICE%"=="7" goto paste_file
if "%CHOICE%"=="8" goto live_info
if "%CHOICE%"=="9" goto end

echo Ugyldig valg. Proev igjen.
timeout /t 2 >nul
goto menu

:full_lab
echo Starter full lab mode...
start "paper" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\02_paper.bat"
start "operator-status" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\05_status.bat"
start "review" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\09_review_candidates.bat"
echo Full lab mode startet i egne vinduer.
echo Paper er kontinuerlig. Research kjores separat som batch ved behov.
pause
goto menu

:paper_only
start "paper" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\02_paper.bat"
echo Paper engine startet i eget vindu.
pause
goto menu

:research_once
call scripts\03_research.bat
goto menu

:status
start "operator-status" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\05_status.bat"
goto menu

:review
start "review" cmd /k "cd /d ^"%REPO_ROOT%^" && call scripts\09_review_candidates.bat"
goto menu

:exports
if not exist "runtime\llm_exports" mkdir "runtime\llm_exports"
start "" explorer "runtime\llm_exports"
goto menu

:paste_file
if exist "runtime\llm_exports\paste_to_llm.md" (
    start "" "runtime\llm_exports\paste_to_llm.md"
) else (
    echo Fant ikke runtime\llm_exports\paste_to_llm.md enda.
    echo Kjor research eller export-bundle for aa generere filen.
    pause
)
goto menu

:live_info
cls
echo ======================================================================
echo ⚠️  LIVE MODE ER SEPARAT OG BEVISST
echo ======================================================================
echo Lab mode er paper-first og starter IKKE live automatisk.
echo For live maa du bruke scripts\01_live.bat eksplisitt,
echo med korrekt config, nøkler og sjekkliste.
echo Les LIVE_CHECKLIST.md foer live-operasjon.
echo ======================================================================
pause
goto menu

:end
echo Ha det, Lord Heibo. 👑
exit /b 0
