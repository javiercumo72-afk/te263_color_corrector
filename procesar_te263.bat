@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem ============================================================
rem CONFIGURACION
rem El BAT pedira las rutas al iniciar.
rem ============================================================
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

:ASK_INPUT_DIR
echo Ingresa el DIRECTORIO ORIGEN.
echo Debe ser la carpeta donde estan las subcarpetas con imagenes.
set /p "INPUT_DIR=Directorio origen: "
set "INPUT_DIR=%INPUT_DIR:"=%"
if "%INPUT_DIR%"=="" (
    echo ERROR: debes ingresar un directorio origen.
    echo.
    goto ASK_INPUT_DIR
)
if not exist "%INPUT_DIR%" (
    echo ERROR: no existe el directorio origen:
    echo "%INPUT_DIR%"
    echo.
    goto ASK_INPUT_DIR
)

:ASK_OUTPUT_DIR
echo.
echo Ingresa el DIRECTORIO DESTINO para los archivos TIFF corregidos.
set /p "OUTPUT_DIR=Directorio destino TIFF: "
set "OUTPUT_DIR=%OUTPUT_DIR:"=%"
if "%OUTPUT_DIR%"=="" (
    echo ERROR: debes ingresar un directorio destino para los TIFF.
    goto ASK_OUTPUT_DIR
)

:ASK_DEBUG_DIR
echo.
echo Ingresa el DIRECTORIO para archivos secundarios.
echo Aqui se guardaran JPG de control y CSV.
set /p "DEBUG_DIR=Directorio secundarios: "
set "DEBUG_DIR=%DEBUG_DIR:"=%"
if "%DEBUG_DIR%"=="" (
    echo ERROR: debes ingresar un directorio para archivos secundarios.
    goto ASK_DEBUG_DIR
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

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if not exist "%DEBUG_DIR%" mkdir "%DEBUG_DIR%"

echo.
echo Procesando...
echo Directorio origen:       "%INPUT_DIR%"
echo Destino TIFF:            "%OUTPUT_DIR%"
echo Archivos secundarios:    "%DEBUG_DIR%"
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
