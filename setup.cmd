@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.12 with Add Python to PATH, then run setup.cmd again.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b 1
if not exist ".env" copy /y ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m pip install -c requirements.lock -e ".[test]"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m copilot.cli seed
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m copilot.cli doctor
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Fill GEMINI_API_KEY in .env, then run run.cmd or press F5 in VS Code.
