@echo off
title Gadgets Mankind - Cloud Web Dashboard
cd /d "%~dp0"
echo ========================================================
echo   GADGETS MANKIND - WEB DASHBOARD & 24/7 SCHEDULER
echo   Opening: http://localhost:10000
echo ========================================================
echo.
timeout /t 2 >nul
start http://localhost:10000
python app.py
pause
