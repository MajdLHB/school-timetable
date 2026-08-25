@echo off
REM ===========================================================
REM   Build the timetable.  Double-click this file.
REM   Ctrl+C at any moment keeps the best result found so far.
REM ===========================================================
cd /d "%~dp0"

echo.
echo  ---------------------------------------------
echo   STEP 1 of 3 - checking your data
echo  ---------------------------------------------
python solver\data.py
if errorlevel 1 (
  echo.
  echo  Your data has problems. Fix them in data\school.xlsx, then run again.
  pause
  exit /b 1
)

echo.
echo  ---------------------------------------------
echo   STEP 2 of 3 - building the timetable
echo   (about 10 minutes - Ctrl+C keeps the best so far)
echo  ---------------------------------------------
REM STRICT MODE (Majd 2026-08-25: "build by them from the start...
REM   crashing hard rules is not livable"): every hard rule is absolute.
REM   Exceptions are IMPOSSIBLE in this mode. Only if the solver PROVES
REM   that no legal timetable exists at all does it retry with declared
REM   exceptions - and then the report says exactly what and why.
REM --workers=2: this machine has 8 GB RAM; more workers can crash.
REM   A later --time=N on the command line still overrides the default.
python solver\solve.py --workers=2 --time=600 %*
if errorlevel 1 (
  echo.
  echo  No timetable was produced. Read the message above.
  pause
  exit /b 1
)

echo.
echo  ---------------------------------------------
echo   STEP 3 of 3 - independent check
echo  ---------------------------------------------
python solver\verify.py
if errorlevel 1 (
  echo.
  echo  ******************************************************
  echo   THE CHECK FAILED. DO NOT USE THIS TIMETABLE.
  echo   Send the message above to whoever maintains the tool.
  echo  ******************************************************
  pause
  exit /b 1
)

echo.
echo  =====================================================
echo   FINISHED.
echo.
echo   1. Read   out\report.md
echo   2. In aSc TimeTables:  File - Import - aSc Timetables XML
echo      choose   out\timetable.xml
echo      press OK on BOTH dialogs
echo  =====================================================
echo.
pause
