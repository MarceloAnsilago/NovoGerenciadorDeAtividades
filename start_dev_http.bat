@echo off
cd /d "%~dp0"
start "" "http://127.0.0.2:8000/"

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" manage.py runserver 127.0.0.2:8000
) else (
  python manage.py runserver 127.0.0.2:8000
)
