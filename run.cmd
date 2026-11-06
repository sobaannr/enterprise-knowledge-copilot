@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  exit /b 1
)
if not exist ".env" copy /y ".env.example" ".env" >nul
echo Open http://127.0.0.1:8000 . Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn copilot.api:app --host 127.0.0.1 --port 8000
