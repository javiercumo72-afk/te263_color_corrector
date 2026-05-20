@echo off
setlocal

rem ============================================================
rem CONFIGURACION
rem Cambia estas rutas antes de ejecutar.
rem ============================================================
set "INPUT_DIR=D:\TLT"
set "OUTPUT_DIR=D:\TLT_CORREGIDAS"
set "DEBUG_DIR=D:\TLT_DEBUG_TE263"
set "MODE=matrix"
set "STRENGTH=1.0"
set "ICC_PROFILE=C:\Windows\System32\spool\drivers\color\AdobeRGB1998.icc"

rem ============================================================
rem EJECUCION
rem ============================================================
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if exist "%PROJECT_DIR%tools\exiftool.exe" (
    set "PATH=%PROJECT_DIR%tools;%PATH%"
)

if exist "%PROJECT_DIR%icc\AdobeRGB1998.icc" (
    set "ICC_PROFILE=%PROJECT_DIR%icc\AdobeRGB1998.icc"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
set "PYTHONPATH=%PROJECT_DIR%src;%PYTHONPATH%"

python -m te263_color_corrector "%INPUT_DIR%" "%OUTPUT_DIR%" ^
  --recursive ^
  --mode "%MODE%" ^
  --strength "%STRENGTH%" ^
  --debug ^
  --debug-dir "%DEBUG_DIR%" ^
  --icc-profile "%ICC_PROFILE%" ^
  --continue-on-error

echo.
echo Finalizado.
echo TIFF finales: "%OUTPUT_DIR%"
echo Debug/CSV:     "%DEBUG_DIR%"
pause

endlocal
