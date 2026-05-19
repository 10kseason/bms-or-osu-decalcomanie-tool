@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0bms_decalcomanie_converter.py"
    exit /b %errorlevel%
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0bms_decalcomanie_converter.py"
    exit /b %errorlevel%
)

echo Python 3 was not found. Install Python 3, then run this file again.
timeout /t 10 >nul
exit /b 1
