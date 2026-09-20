@echo off
cd /d "%~dp0"
echo Starting Shutterstock Article Image Checker - Local V2 with Python 3.12...
if not exist "app_local2.py" (
    echo ERROR: app_local2.py is missing. Run START_SHUTTERSTOCK_CHECKER.bat to download the latest GitHub version.
    pause
    exit /b 1
)
py -3.12 -m streamlit run app_windows.py --server.address localhost --server.port 8501
pause
