# TE263 Color Corrector - paquete portable

## Requisitos en la PC destino

- Windows.
- Python 3.10 o superior instalado y disponible como `python`.
- Acceso a internet la primera vez, para instalar `numpy`, `opencv-python` y `Pillow`.

## Primer uso

1. Descomprime el ZIP en una carpeta local.
2. Ejecuta `instalar_dependencias.bat`.
3. Ejecuta `ejecutar_te263_gui.bat` para usar la interfaz grafica, o `procesar_te263.bat` para el procesamiento por lotes.
4. Cuando el BAT lo pida, ingresa:
   - directorio origen donde estan las subcarpetas con imagenes;
   - directorio destino para los archivos TIFF corregidos;
   - directorio para archivos secundarios JPG/CSV de control.

Puedes pegar rutas con o sin comillas. El directorio origen debe existir. Los
directorios de destino y secundarios se crean automaticamente si no existen.
Si no quieres cambiar las rutas sugeridas, presiona Enter en las tres preguntas.

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
- `ejecutar_te263_gui.bat`: interfaz grafica con seleccion manual de la carta TE263.
- `instalar_dependencias.bat`: crea `.venv` e instala dependencias.
- `src\te263_color_corrector\calibrator.py`: codigo principal.
- `requirements.txt`: dependencias Python.
