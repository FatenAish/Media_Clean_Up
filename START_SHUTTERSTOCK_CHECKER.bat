@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Shutterstock Article Image Checker - Local V2

set "REPO_ZIP=https://github.com/FatenAish/Media_Clean_Up/archive/refs/heads/main.zip"
set "DESKTOP=%USERPROFILE%\Desktop"
set "TARGET=%DESKTOP%\Media_Clean_Up"
set "ZIPFILE=%TEMP%\Media_Clean_Up-main.zip"
set "EXTRACT=%TEMP%\Media_Clean_Up_extract"
set "SOURCE=%EXTRACT%\Media_Clean_Up-main"

echo.
echo ==========================================
echo Shutterstock Article Image Checker V2
echo ==========================================
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher "py" was not found.
    echo Install Python 3.12 first, then run this file again.
    pause
    exit /b 1
)

py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.12 was not found.
    echo Install Python 3.12 first, then run this file again.
    pause
    exit /b 1
)

echo [1/6] Stopping any previous checker on port 8501...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [2/6] Downloading the latest GitHub V2 project...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile '%ZIPFILE%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo.
    echo ERROR: Could not download the GitHub project.
    echo Check your internet connection and try again.
    pause
    exit /b 1
)

echo [3/6] Extracting the project...
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >nul 2>&1
mkdir "%EXTRACT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%ZIPFILE%' -DestinationPath '%EXTRACT%' -Force"
if errorlevel 1 (
    echo ERROR: Could not extract the project.
    pause
    exit /b 1
)

if not exist "%SOURCE%\app_windows.py" (
    echo ERROR: app_windows.py was not found in the downloaded project.
    pause
    exit /b 1
)
if not exist "%SOURCE%\app_local2.py" (
    echo ERROR: app_local2.py was not found in the downloaded project.
    pause
    exit /b 1
)

echo [4/6] Updating local project safely...
if not exist "%TARGET%" mkdir "%TARGET%" >nul 2>&1
robocopy "%SOURCE%" "%TARGET%" /E /R:3 /W:1 /XD work .git __pycache__ /XF *.pyc >nul
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
    echo ERROR: Could not update the local project. Robocopy code: %RC%
    pause
    exit /b 1
)

if not exist "%TARGET%\app_windows.py" (
    echo ERROR: app_windows.py is missing after update.
    pause
    exit /b 1
)
if not exist "%TARGET%\app_local2.py" (
    echo ERROR: app_local2.py is missing after update.
    pause
    exit /b 1
)

cd /d "%TARGET%"

echo [5/6] Installing required Python packages...
py -3.12 -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Python package installation failed.
    pause
    exit /b 1
)

echo [6/6] Starting Local V2...
echo.
echo Project folder:
echo %TARGET%
echo.
echo Keep this window open while using the checker.
echo.

py -3.12 -m streamlit run app_windows.py --server.address localhost --server.port 8501

echo.
echo Streamlit stopped.
pause
