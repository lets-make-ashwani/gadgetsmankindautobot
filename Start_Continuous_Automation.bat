@echo off
title Gadgets Mankind - Continuous 24/7 Automation Loop
cd /d "%~dp0"
echo ========================================================
echo   GADGETS MANKIND - 24/7 CONTINUOUS AUTOPILOT
echo   (Interval: Every 3 Hours)
echo ========================================================
echo.
python pipeline.py
pause
