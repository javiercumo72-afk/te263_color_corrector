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

Alternativa sin instalar el comando:

```powershell
python -m te263_color_corrector entrada.tif salida.tif --debug
```

## Salidas de debug

Con `--debug`, junto al TIFF corregido se generan:

- `*_debug_chart_before.jpg`: carta detectada antes de corregir.
- `*_debug_chart_after.jpg`: carta corregida.
- `*_patch_report.csv`: mediciones RGB antes/despues y objetivos Lab/sRGB.

## Notas

Los valores Lab de referencia estan incluidos como valores por defecto. Si se
consiguen los valores medidos de una carta TE263 concreta, conviene sustituirlos
en `src/te263_color_corrector/calibrator.py`.
