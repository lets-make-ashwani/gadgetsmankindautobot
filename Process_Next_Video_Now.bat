@echo off
title Gadgets Mankind - Process Next Video
cd /d "%~dp0"
echo ========================================================
echo   GADGETS MANKIND AUTOMATION - SINGLE VIDEO RUN
echo ========================================================
echo.
python pipeline.py --run-once
echo.
echo Cycle finished.
pause
