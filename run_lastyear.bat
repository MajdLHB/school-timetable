@echo off
REM ===========================================================
REM   THE DUEL - solve LAST YEAR's school (rebuilt from its own
REM   aSc file) and compare with the hand-made table, same ruler.
REM   2 hours. Ctrl+C keeps the best found so far.
REM ===========================================================
cd /d "%~dp0"

echo.
echo  STEP 1 of 4 - checking last year's rebuilt data
python solver\data.py data\school_lastyear.xlsx
if errorlevel 1 ( pause & exit /b 1 )

echo.
echo  STEP 2 of 4 - solving last year's school (2 HOURS, STRICT)
python solver\solve.py data\school_lastyear.xlsx --workers=2 --time=7200 %*
if errorlevel 1 ( pause & exit /b 1 )

echo.
echo  STEP 3 of 4 - independent check
python solver\verify.py data\school_lastyear.xlsx
if errorlevel 1 (
  echo  THE CHECK FAILED - DO NOT USE. Tell the maintainer.
  pause & exit /b 1
)

echo.
echo  STEP 4 of 4 - THE COMPARISON, same ruler both tables
echo  ---- the hand-made table (work-in-progress copy): ----
python tools\score_table.py
echo  ---- the solver's table: ----
python tools\score_table.py out\timetable.xml
echo.
echo  Lower is better on every line. out\view.html to inspect.
pause
