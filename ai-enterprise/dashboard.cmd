@echo off
rem Command Center lokalt pa Windows med ett enda kommando (Command Center Del 0, 2026-11-09).
rem Dubbelklicka, eller kor "ai-enterprise\dashboard.cmd" fran valfri mapp. "dashboard.cmd --lan" for mobilen.
rem Det som stoppade D1: PYTHONPATH maste sattas for hand (och PowerShell-syntaxen fungerade inte i Git Bash),
rem fonstret stangdes vid fel, och en upptagen port gav bara ett felmeddelande. Allt det skots har.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.11 or later was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  goto :fail
)

%PY% -m aie dashboard has-code >nul 2>nul
if errorlevel 1 (
  echo No access code is set yet.
  set /p "FOUNDER=Who are you (Yorgo or Robin)? "
  %PY% -m aie dashboard set-code --founder "!FOUNDER!"
  if errorlevel 1 goto :fail
)

%PY% -m aie simulate status 2>nul | findstr /c:"Ingen simuleringsk" >nul
if not errorlevel 1 (
  echo There is no local SIM data yet. Creating test data in SIM ^(about 10 seconds^)...
  %PY% scripts\seed_sim.py
  if errorlevel 1 goto :fail
)

%PY% -m aie dashboard --open %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Command Center could not start. The reason is shown above.
pause
exit /b 1
