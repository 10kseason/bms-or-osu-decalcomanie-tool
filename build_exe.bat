@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher py.exe was not found.
    timeout /t 10 >nul
    exit /b 1
)

py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name BMS_Decalcomanie_Tool BMS_Decalcomanie_Tool.pyw
exit /b %errorlevel%
