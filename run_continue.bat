@echo off
REM ===========================================================
REM   CONTINUE - picks up the best from the last run (solution.json)
REM   and improves it 15 more minutes. Ctrl+C keeps
REM   the best timetable found so far. Same checks as run.bat.
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
echo   STEP 2 of 3 - building the timetable (15 MIN, CONTINUES FROM THE LAST SAVED BEST)
echo   Every hard rule absolute - no exceptions possible.
echo   Ctrl+C keeps the best found so far.
echo  ---------------------------------------------
python solver\solve.py --workers=2 --continue --time=900 %*
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
  echo  ******************************************************
  pause
  exit /b 1
)

echo.
echo  =====================================================
echo   FINISHED. Read out\report.md, import out\timetable.xml
echo   (aSc project must be set to 2 WEEKS + 6 days).
echo  =====================================================
pause
