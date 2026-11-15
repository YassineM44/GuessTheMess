@echo off
setlocal
cd /d "%~dp0.."
title Guess The Mess - Game Server
if not exist ".venv\Scripts\python.exe" (
    echo Please double-click Setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import aiohttp, aiortc" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Please run Setup.bat again.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" server.py
echo.
echo The server has stopped.
pause
