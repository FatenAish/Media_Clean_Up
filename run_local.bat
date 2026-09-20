@echo off
cd /d "%~dp0"
echo Starting local Shutterstock checker with Python 3.12...
py -3.12 -m streamlit run app_local.py
pause
