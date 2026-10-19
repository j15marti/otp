@echo off
rem Double-click to open OTPNET.
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python is not installed. Your browser will open the download page.
  echo Install it, tick "Add python.exe to PATH", then double-click this file again.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% install_deps.py --quiet || (pause & exit /b 1)
%PY% otpnet.py
pause
