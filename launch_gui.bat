@echo off
rem ---- CZI figure maker launcher ----
rem If you use a conda env, uncomment the next line and set the env name:
rem call conda activate cellcount

chcp 65001 > nul
cd /d "%~dp0"

rem ---- Find a real Python (skip the Microsoft Store "python" placeholder) ----
set "PYEXE="
rem 1) an activated conda env / venv
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYEXE=%CONDA_PREFIX%\python.exe"
if not defined PYEXE if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYEXE=%VIRTUAL_ENV%\Scripts\python.exe"
rem 2) Python install manager (python.org) shim
if not defined PYEXE if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PYEXE=%LOCALAPPDATA%\Python\bin\python.exe"
rem 3) python on PATH, excluding the WindowsApps placeholder
if not defined PYEXE for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined PYEXE set "PYEXE=%%P"
rem 4) the py launcher
if not defined PYEXE (where py >nul 2>nul && set "PYEXE=py")

if not defined PYEXE (
  echo Python was not found.
  echo Install Python 3.11 or later from https://www.python.org/ , or use the conda env
  echo by removing "rem " from the "call conda activate cellcount" line in this file.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%

rem ---- Check required packages ----
"%PYEXE%" -c "import numpy, PIL, czifile, qtpy, pandas, scipy, skimage, cv2, pptx" 2>nul
if errorlevel 1 (
  echo.
  echo Some packages are missing. Run this once, then start again:
  echo     "%PYEXE%" -m pip install -r requirements.txt
  echo.
  "%PYEXE%" -c "import numpy, PIL, czifile, qtpy, pandas, scipy, skimage, cv2, pptx"
  pause
  exit /b 1
)

"%PYEXE%" czi_figure_gui.py %*
if errorlevel 1 (
  echo.
  echo ---- Exited with an error. See the message above. ----
  pause
)
