# TE263 Color Corrector

Proyecto Python para corregir color en escaneos o fotografias usando una carta
Image Engineering Scan Reference Chart TE263.

El nucleo parte de `calibrar_te263_v2.py` y conserva sus modos originales:

- `hybrid`: recomendado; matriz RGB 3x3 sin offset y curva neutral.
- `matrix`: solo matriz RGB 3x3 sin offset.
- `neutral`: solo ajuste de escala de grises.

## Instalacion

Desde esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Tambien puedes instalar dependencias sin modo editable:

```powershell
python -m pip install -r requirements.txt
```

## Uso

Procesar una imagen:

```powershell
te263-correct entrada.tif salida.tif --mode hybrid --strength 1.0 --debug
```

Procesar una carpeta:

```powershell
te263-correct carpeta_entrada carpeta_salida --recursive --mode hybrid --debug
```

Procesar una carpeta y continuar si alguna imagen falla:

```powershell
te263-correct carpeta_entrada carpeta_salida --recursive --mode hybrid --debug --continue-on-error
```

Procesar una carpeta dejando TIFF finales en una carpeta y JPG/CSV de diagnostico
en otra:

```powershell
te263-correct carpeta_entrada carpeta_salida --recursive --mode matrix --debug --debug-dir carpeta_debug --continue-on-error
```

Alternativa sin instalar el comando:

```powershell
python -m te263_color_corrector entrada.tif salida.tif --debug
```

## Salidas de debug

Con `--debug`, junto al TIFF corregido se generan:

- `*_debug_chart_before.jpg`: carta detectada antes de corregir.
- `*_debug_chart_after.jpg`: carta corregida.
- `*_patch_report.csv`: mediciones RGB antes/despues y objetivos Lab/sRGB.

Si se indica `--debug-dir`, esos JPG/CSV se guardan en esa carpeta separada y
los TIFF finales quedan solos en la carpeta de salida.

## Salida final

Los TIFF finales se guardan sin compresion, a 300x300 DPI, en RGB de 24 bits.
El programa copia metadatos de la imagen fuente con ExifTool y conserva el perfil
ICC indicado con `--icc-profile`; por defecto usa Adobe RGB 1998 desde:

```text
C:\Windows\System32\spool\drivers\color\AdobeRGB1998.icc
```

Para ejecuciones por lotes con rutas editables, usa `procesar_te263.bat`.

## Deteccion de la carta

El detector busca la TE263 en la parte inferior de la imagen, tanto si aparece
centrada como desplazada hacia la derecha. La carta se endereza con una
transformacion de perspectiva y se valida reconociendo las dos flechas negras de
los extremos. Esas flechas se usan como anclas horizontales para fijar la
posicion esperada de los dos grupos de parches de color.

## Notas

Los valores Lab de referencia estan incluidos como valores por defecto. Si se
consiguen los valores medidos de una carta TE263 concreta, conviene sustituirlos
en `src/te263_color_corrector/calibrator.py`.
