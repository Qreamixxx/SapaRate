@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
echo Installing requirements (first run only takes a minute)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python not found or install failed. Install Python 3.10+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)
set HOST=0.0.0.0
python run.py
pause
