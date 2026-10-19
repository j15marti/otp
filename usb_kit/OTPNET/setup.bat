@echo off
rem One-time setup for this drive on Windows.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% install_deps.py && %PY% otpnet.py doctor
pause
