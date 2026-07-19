@echo off
setlocal
set PROJECT_ROOT=%~dp0
if not exist "%PROJECT_ROOT%venv\Scripts\activate.bat" (
  echo Virtual environment not found. Create one with: python -m venv venv
  exit /b 1
)
call "%PROJECT_ROOT%venv\Scripts\activate.bat"
python -m pip install -r "%PROJECT_ROOT%requirements.txt"
python "%PROJECT_ROOT%manage.py" runserver
