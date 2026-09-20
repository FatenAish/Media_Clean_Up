@echo off
cd /d "%~dp0"
echo Installing local requirements with Python 3.12...
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
echo.
echo Installation complete. Double-click run_local.bat to start.
pause
