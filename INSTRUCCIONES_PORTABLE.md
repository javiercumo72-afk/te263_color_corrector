# TE263 Color Corrector - paquete portable

## Requisitos en la PC destino

- Windows.
- Python 3.10 o superior instalado y disponible como `python`.
- Acceso a internet la primera vez, para instalar `numpy`, `opencv-python` y `Pillow`.

## Primer uso

1. Descomprime el ZIP en una carpeta local.
2. Ejecuta `instalar_dependencias.bat`.
3. Ejecuta `procesar_te263.bat`.
4. Cuando el BAT lo pida, ingresa:
   - carpeta donde estan las subcarpetas con imagenes;
   - carpeta destino para los TIFF corregidos;
   - carpeta para archivos secundarios JPG/CSV de control.

Si presionas Enter, el BAT usa los valores sugeridos.

## Perfil ICC y metadatos

El programa genera TIFF sin compresion, 300 DPI, RGB 24 bit.

Para incrustar Adobe RGB, el BAT usa primero:

```text
icc\AdobeRGB1998.icc
```

Si ese archivo no existe, usa el perfil instalado en Windows:

```text
C:\Windows\System32\spool\drivers\color\AdobeRGB1998.icc
```

Para conservar metadatos, el BAT usa `tools\exiftool.exe` si esta incluido en
el paquete. Si no esta, instala ExifTool en la PC destino y asegurate de que el
comando `exiftool` funcione desde CMD o PowerShell.

## Archivos importantes

- `procesar_te263.bat`: ejecucion por lotes; pide rutas al iniciar.
- `instalar_dependencias.bat`: crea `.venv` e instala dependencias.
- `src\te263_color_corrector\calibrator.py`: codigo principal.
- `requirements.txt`: dependencias Python.
