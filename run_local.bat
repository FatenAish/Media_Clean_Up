@echo off
cd /d "%~dp0"
echo Starting Shutterstock Article Image Checker with Python 3.12...
py -3.12 -m streamlit run app.py
pause
