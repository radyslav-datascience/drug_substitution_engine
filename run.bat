@echo off
REM =============================================================================
REM Drug Substitution Engine — Windows launcher
REM =============================================================================
REM Подвійний клік запускає повний pipeline:
REM   discover → Phase A (parallel × 6 workers) → Phase B → Phase C → 4 final files
REM =============================================================================

setlocal

REM Перейти у директорію цього .bat файлу
cd /d "%~dp0"

REM -----------------------------------------------------------------------------
REM Виявлення Python — fallback chain (працює і на машині автора, і на свіжому
REM клоні репо без жодних правок):
REM   1) Явний override через env var DRUG_SUB_PYTHON (повний шлях до python.exe).
REM   2) Локальний venv .venv\ або venv\ всередині проекту.
REM   3) Особистий venv автора (D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\)
REM      — спрацює тільки на машині розробника, для всіх інших — пропускається.
REM   4) `python` із PATH.
REM Hint для нових клонів: створи venv у `.venv\` та постав requirements.txt:
REM     python -m venv .venv
REM     .venv\Scripts\python.exe -m pip install -r requirements.txt
REM -----------------------------------------------------------------------------

set "PYTHON_EXE="

if defined DRUG_SUB_PYTHON (
    if exist "%DRUG_SUB_PYTHON%" set "PYTHON_EXE=%DRUG_SUB_PYTHON%"
)

if not defined PYTHON_EXE (
    if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    if exist "venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    if exist "D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\Scripts\python.exe" (
        set "PYTHON_EXE=D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\Scripts\python.exe"
    )
)

REM `where python` + delayed-expansion check, бо %ERRORLEVEL% всередині
REM parenthetical-блоку розгортається у момент парсингу, а не після `where`.
if not defined PYTHON_EXE (
    where python >nul 2>nul && set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo.
    echo [ERROR] Python interpreter not found.
    echo.
    echo Tried, in order:
    echo   1) %%DRUG_SUB_PYTHON%%               (env var override)
    echo   2) .venv\Scripts\python.exe          (local venv)
    echo   3) venv\Scripts\python.exe           (alternate local venv)
    echo   4) D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\Scripts\python.exe (author's venv)
    echo   5) python                             (system PATH)
    echo.
    echo Set up a venv:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo ====================================================================
echo  Drug Substitution Engine — Full Pipeline
echo ====================================================================
echo  Python:  %PYTHON_EXE%
echo  CWD:     %CD%
echo.
echo  Pipeline phases:
echo    A0: Discover markets
echo    A:  Per-market processing (A1+A2+A3+A4 parallel)
echo    B:  Cross-market aggregation
echo    C:  Final export (2 CSV + 2 XLSX for Power BI)
echo ====================================================================
echo.

REM Запуск pipeline
"%PYTHON_EXE%" -m pipeline.full_run %*

set "EXIT_CODE=%ERRORLEVEL%"

echo.
if %EXIT_CODE% EQU 0 (
    echo ====================================================================
    echo  SUCCESS — Pipeline completed.
    echo  Final files: results\final\
    echo ====================================================================
) else (
    echo ====================================================================
    echo  FAILURE — Pipeline returned exit code %EXIT_CODE%.
    echo  Check log file in: logs\
    echo ====================================================================
)
echo.

REM Залишити вікно відкритим, щоб користувач прочитав результати
pause
exit /b %EXIT_CODE%
