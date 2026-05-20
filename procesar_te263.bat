@echo off
setlocal

rem ============================================================
rem CONFIGURACION
rem Puedes presionar Enter para usar los valores sugeridos.
rem ============================================================
set "DEFAULT_INPUT_DIR=D:\TLT"
set "DEFAULT_OUTPUT_DIR=D:\TLT_CORREGIDAS"
set "DEFAULT_DEBUG_DIR=D:\TLT_DEBUG_TE263"
set "MODE=matrix"
set "STRENGTH=1.0"
set "ICC_PROFILE=C:\Windows\System32\spool\drivers\color\AdobeRGB1998.icc"

rem ============================================================
rem EJECUCION
rem ============================================================
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo.
echo ============================================================
echo TE263 Color Corrector
echo ============================================================
echo.
echo Ingresa la carpeta donde estan las subcarpetas con imagenes.
echo Si presionas Enter se usara: "%DEFAULT_INPUT_DIR%"
set /p "INPUT_DIR=Carpeta de entrada: "
if "%INPUT_DIR%"=="" set "INPUT_DIR=%DEFAULT_INPUT_DIR%"

echo.
echo Ingresa la carpeta destino para los TIFF corregidos.
echo Si presionas Enter se usara: "%DEFAULT_OUTPUT_DIR%"
set /p "OUTPUT_DIR=Carpeta destino TIFF: "
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=%DEFAULT_OUTPUT_DIR%"

echo.
echo Ingresa la carpeta para archivos secundarios JPG/CSV de control.
echo Si presionas Enter se usara: "%DEFAULT_DEBUG_DIR%"
set /p "DEBUG_DIR=Carpeta secundarios/debug: "
if "%DEBUG_DIR%"=="" set "DEBUG_DIR=%DEFAULT_DEBUG_DIR%"

if not exist "%INPUT_DIR%" (
    echo.
    echo ERROR: no existe la carpeta de entrada:
    echo "%INPUT_DIR%"
    pause
    exit /b 1
)

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

echo.
echo Procesando...
echo Entrada:       "%INPUT_DIR%"
echo TIFF finales:  "%OUTPUT_DIR%"
echo Secundarios:   "%DEBUG_DIR%"
echo.

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
