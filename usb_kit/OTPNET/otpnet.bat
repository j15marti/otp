@echo off
where py >nul 2>nul && (py -3 "%~dp0otpnet.py" %*) || (python "%~dp0otpnet.py" %*)
