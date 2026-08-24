@echo off
REM ===========================================================
REM   Check data\school.xlsx for mistakes. Changes nothing.
REM   Safe to run any time, as often as you like.
REM ===========================================================
cd /d "%~dp0"
python solver\data.py
echo.
pause
