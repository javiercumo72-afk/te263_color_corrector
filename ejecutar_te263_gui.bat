@echo off
setlocal

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
set "PYTHONPATH=%PROJECT_DIR%src;%PYTHONPATH%"
python -m te263_color_corrector.gui

endlocal
