@echo off
setlocal
cd /d "%~dp0.."
title Guess The Mess - Setup
echo.
echo   GUESS THE MESS - One-time setup
echo   Internet is needed to download the Python packages.
echo.
if exist ".venv\Scripts\python.exe" goto install
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    goto checkvenv
)
python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)" >nul 2>&1
if errorlevel 1 goto nopython
python -m venv .venv
:checkvenv
if not exist ".venv\Scripts\python.exe" goto failed
:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
echo.
echo   Setup complete! Double-click "Start Server.bat" to play.
echo.
pause
exit /b 0
:nopython
echo   Install Python 3.12 (64-bit) from https://www.python.org/downloads/
echo   Enable "Add python.exe to PATH" in the installer.
echo   Then run this setup again. Python 3.10-3.13 is supported.
pause
exit /b 1
:failed
echo.
echo   Setup failed. Read the error above.
echo   Check your internet connection and Python installation, then retry.
pause
exit /b 1
