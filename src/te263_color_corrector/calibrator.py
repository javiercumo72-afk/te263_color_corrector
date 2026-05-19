#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Corrección de color para escaneos/fotografías con carta
Image Engineering Scan Reference Chart TE263.

Mejoras de esta versión:
- Detección más estable de la fila de parches.
- ROIs de parches calculadas dinámicamente a partir de la carta rectificada.
- Corrección "hybrid" recomendada: matriz RGB 3x3 sin offset + curva neutral.
  Esto evita que los grises oscuros 16-20 se vayan a RGB 0,0,0.

Uso recomendado:
    python calibrar_te263_v2.py entrada.tif salida.tif --mode hybrid --strength 1.0 --debug

Procesar carpeta:
    python calibrar_te263_v2.py carpeta_entrada carpeta_salida --recursive --mode hybrid --debug

Requisitos:
    pip install opencv-python numpy pillow
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import cv2
import numpy as np
from PIL import Image


# ============================================================
# Valores CIE Lab por defecto para TE263
# Sustituir por los valores individuales de tu carta si se consiguen.
# ============================================================

REFERENCE_LAB: Dict[str, Tuple[float, float, float]] = {
    "C1": (46.0, 64.0, 34.0),
    "B1": (53.0, -45.0, 38.0),
    "A1": (18.0, 24.0, -61.0),
    "C2": (48.0, -34.0, -31.0),
    "B2": (49.0, 56.0, -14.0),
    "A2": (82.0, 3.0, 90.0),
    "B5": (64.0, 20.0, 19.0),
    "A5": (32.0, 24.0, 32.0),
    "20": (5.0, 0.0, 0.0),
    "18": (10.0, 0.0, 0.0),
    "17": (15.0, 0.0, 0.0),
    "16": (20.0, 0.0, 0.0),
    "11": (45.0, 0.0, 0.0),
    "10": (50.0, 0.0, 0.0),
    "09": (55.0, 0.0, 0.0),
    "03": (85.0, 0.0, 0.0),
    "02": (90.0, 0.0, 0.0),
    "01": (95.0, 0.0, 0.0),
    "C7": (86.0, -19.0, -1.0),
    "B7": (85.0, 13.0, 0.0),
    "A7": (85.0, -2.0, -9.0),
    "C8": (87.0, 10.0, 18.0),
    "B8": (85.0, -11.0, 26.0),
    "A8": (86.0, 13.0, 7.0),
    "C9": (85.0, -14.0, -9.0),
    "B9": (85.0, 4.0, -6.0),
}

LEFT_LABELS = ["C1", "B1", "A1", "C2", "B2", "A2", "B5", "A5", "20", "18", "17", "16", "11"]
RIGHT_LABELS = ["10", "09", "03", "02", "01", "C7", "B7", "A7", "C8", "B8", "A8", "C9", "B9"]
ALL_LABELS = LEFT_LABELS + RIGHT_LABELS
NEUTRAL_LABELS = ["20", "18", "17", "16", "11", "10", "09", "03", "02", "01"]
SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
TARGET_DPI = (300.0, 300.0)
DEFAULT_ADOBE_RGB_PROFILE = Path(r"C:\Windows\System32\spool\drivers\color\AdobeRGB1998.icc")
PATCH_TEMPLATE_LT = 2345.0
PATCH_TEMPLATE_P1 = 100.0
PATCH_TEMPLATE_LEFT_GROUP_WIDTH = 890.0
PATCH_TEMPLATE_P2 = 1362.0
PATCH_TEMPLATE_RIGHT_GROUP_WIDTH = 880.0
PATCH_SAMPLE_FRACTION_X = 0.58
PATCH_SAMPLE_FRACTION_Y = 0.58
PATCH_SAMPLE_Y_OFFSET = -20.0


@dataclass(frozen=True)
class ChartAnchors:
    left_arrow: Tuple[int, int, int, int]
    right_arrow: Tuple[int, int, int, int]
    confidence: float

    @property
    def left_center(self) -> Tuple[float, float]:
        x, y, w, h = self.left_arrow
        return x + w / 2.0, y + h / 2.0

    @property
    def right_center(self) -> Tuple[float, float]:
        x, y, w, h = self.right_arrow
        return x + w / 2.0, y + h / 2.0


# ============================================================
# Conversión colorimétrica Lab D50 -> sRGB D65
# ============================================================

def lab_to_xyz_d50(L: float, a: float, b: float) -> np.ndarray:
    Xn, Yn, Zn = 0.96422, 1.00000, 0.82521
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    delta = 6.0 / 29.0

    def inv_f(t: np.ndarray | float) -> np.ndarray:
        t = np.asarray(t, dtype=np.float64)
        return np.where(t > delta, t ** 3, 3 * delta ** 2 * (t - 4.0 / 29.0))

    return np.array([Xn * inv_f(fx), Yn * inv_f(fy), Zn * inv_f(fz)], dtype=np.float64)


def adapt_d50_to_d65(xyz_d50: np.ndarray) -> np.ndarray:
    M = np.array([
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ], dtype=np.float64)
    M_inv = np.linalg.inv(M)
    white_d50 = np.array([0.96422, 1.00000, 0.82521])
    white_d65 = np.array([0.95047, 1.00000, 1.08883])
    D = np.diag((M @ white_d65) / (M @ white_d50))
    return M_inv @ D @ M @ xyz_d50


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.04045, rgb / 12.92, np.power((rgb + 0.055) / 1.055, 2.4))


def xyz_d65_to_srgb(xyz_d65: np.ndarray) -> np.ndarray:
    M = np.array([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ], dtype=np.float64)
    return linear_to_srgb(M @ xyz_d65)


def lab_to_srgb(L: float, a: float, b: float) -> np.ndarray:
    return xyz_d65_to_srgb(adapt_d50_to_d65(lab_to_xyz_d50(L, a, b)))


# ============================================================
# Lectura, DPI y guardado
# ============================================================

def read_rgb_image(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"No se pudo leer la imagen: {path}")

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    if img.dtype not in (np.uint8, np.uint16):
        raise RuntimeError(f"Tipo de imagen no soportado: {img.dtype}. Usa 8 o 16 bits por canal.")
    return img


def get_dpi(path: Path) -> Tuple[float, float]:
    try:
        with Image.open(path) as im:
            dpi = im.info.get("dpi", (300.0, 300.0))
            return float(dpi[0]), float(dpi[1])
    except Exception:
        return 300.0, 300.0


def to_rgb24(img_rgb: np.ndarray) -> np.ndarray:
    if img_rgb.dtype == np.uint8:
        return img_rgb
    if img_rgb.dtype == np.uint16:
        return np.clip(img_rgb / 257.0 + 0.5, 0, 255).astype(np.uint8)
    return np.clip(img_rgb, 0, 255).astype(np.uint8)


def read_icc_profile(path: Path | None) -> bytes | None:
    if path is None:
        return None
    if not path.exists():
        raise RuntimeError(f"No existe el perfil ICC: {path}")
    return path.read_bytes()


def save_tiff_uncompressed(
    path: Path,
    img_rgb: np.ndarray,
    dpi: Tuple[float, float],
    icc_profile_path: Path | None,
) -> None:
    img24 = to_rgb24(img_rgb)
    kwargs = {"dpi": dpi}
    icc_profile = read_icc_profile(icc_profile_path)
    if icc_profile is not None:
        kwargs["icc_profile"] = icc_profile
    Image.fromarray(img24, mode="RGB").save(path, format="TIFF", compression="raw", **kwargs)


def copy_source_metadata(source_path: Path, output_path: Path) -> None:
    exiftool = shutil.which("exiftool")
    if exiftool is None:
        print("AVISO: ExifTool no esta disponible; no se copiaron metadatos de la fuente.")
        return

    cmd = [
        exiftool,
        "-overwrite_original",
        "-TagsFromFile",
        str(source_path),
        "-all:all",
        "--ICC_Profile:all",
        "--XResolution",
        "--YResolution",
        "--ResolutionUnit",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"No se pudieron copiar metadatos con ExifTool: {message}")


def normalize_image_to_dpi(
    img_rgb: np.ndarray,
    dpi: Tuple[float, float],
    target_dpi: Tuple[float, float] = TARGET_DPI,
) -> Tuple[np.ndarray, Tuple[float, float]]:
    dpi_x, dpi_y = dpi
    target_x, target_y = target_dpi
    if dpi_x <= 0 or dpi_y <= 0:
        dpi_x, dpi_y = target_x, target_y

    if abs(dpi_x - target_x) < 0.5 and abs(dpi_y - target_y) < 0.5:
        return img_rgb, target_dpi

    scale_x = target_x / dpi_x
    scale_y = target_y / dpi_y
    new_w = max(1, int(round(img_rgb.shape[1] * scale_x)))
    new_h = max(1, int(round(img_rgb.shape[0] * scale_y)))
    interpolation = cv2.INTER_AREA if scale_x < 1.0 or scale_y < 1.0 else cv2.INTER_CUBIC
    normalized = cv2.resize(img_rgb, (new_w, new_h), interpolation=interpolation)
    return normalized.astype(img_rgb.dtype, copy=False), target_dpi


# ============================================================
# Utilidades de detección
# ============================================================

def order_points_clockwise(points: np.ndarray) -> np.ndarray:
    s = points.sum(axis=1)
    diff = np.diff(points, axis=1).ravel()
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = points[np.argmin(s)]       # top-left
    ordered[2] = points[np.argmax(s)]       # bottom-right
    ordered[1] = points[np.argmin(diff)]    # top-right
    ordered[3] = points[np.argmax(diff)]    # bottom-left
    return ordered


def smooth_1d(x: np.ndarray, window: int = 9) -> np.ndarray:
    if window <= 1:
        return x.astype(np.float32)
    window = int(window)
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(x.astype(np.float32), kernel, mode="same")


def intervals_from_mask(mask: np.ndarray, min_width: int = 5) -> List[Tuple[int, int]]:
    intervals: List[Tuple[int, int]] = []
    start = None
    for i, value in enumerate(mask.astype(bool)):
        if value and start is None:
            start = i
        if (not value or i == len(mask) - 1) and start is not None:
            end = i - 1 if not value else i
            if end - start + 1 >= min_width:
                intervals.append((start, end))
            start = None
    return intervals


def as_uint8_rgb(img_rgb: np.ndarray) -> np.ndarray:
    return (img_rgb / 257).astype(np.uint8) if img_rgb.dtype == np.uint16 else img_rgb


def warp_chart_from_corners(img_rgb: np.ndarray, corners: np.ndarray) -> np.ndarray:
    out_w, out_h = 2500, 310
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(img_rgb, M, (out_w, out_h), flags=cv2.INTER_CUBIC)


def estimate_bottom_edge_angle(chart_rgb: np.ndarray) -> float | None:
    img8 = as_uint8_rgb(chart_rgb)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape[:2]
    roi_y0 = int(h * 0.62)
    roi = gray[roi_y0:h]

    edges = cv2.Canny(roi, 40, 120)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=70,
        minLineLength=max(250, int(w * 0.20)),
        maxLineGap=40,
    )
    if lines is None:
        return None

    candidates: List[Tuple[float, float]] = []
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = map(float, line)
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if abs(angle) > 6.0:
            continue
        y_mean = roi_y0 + (y1 + y2) / 2.0
        if y_mean < h * 0.70:
            continue
        length = float(np.hypot(dx, dy))
        candidates.append((length, angle))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def level_chart_by_bottom_edge(chart_rgb: np.ndarray) -> np.ndarray:
    angle = estimate_bottom_edge_angle(chart_rgb)
    if angle is None or abs(angle) < 0.05:
        return chart_rgb

    h, w = chart_rgb.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        chart_rgb,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def find_light_chart_bounds(chart_rgb: np.ndarray) -> Tuple[int, int, int, int]:
    img8 = as_uint8_rgb(chart_rgb)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)
    mask = (gray > 105).astype(np.uint8) * 255
    h, w = gray.shape[:2]

    col_score = smooth_1d((mask > 0).mean(axis=0), 31)
    row_score = smooth_1d((mask > 0).mean(axis=1), 9)
    col_intervals = intervals_from_mask(col_score > 0.46, min_width=max(200, int(w * 0.35)))
    row_intervals = intervals_from_mask(row_score > 0.40, min_width=max(50, int(h * 0.35)))
    if not col_intervals or not row_intervals:
        return 0, 0, w, h

    x0 = min(item[0] for item in col_intervals)
    x1 = max(item[1] for item in col_intervals)
    y0, y1 = max(row_intervals, key=lambda item: item[1] - item[0])
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def find_bottom_chart_span(chart_rgb: np.ndarray) -> Tuple[int, int]:
    """Mide la longitud horizontal de la carta usando su franja inferior."""
    img8 = as_uint8_rgb(chart_rgb)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape[:2]

    y0 = int(h * 0.64)
    y1 = int(h * 0.96)
    strip = gray[y0:y1]
    if strip.size == 0:
        return 0, w

    light = ((strip > 105) & (strip < 252)).astype(np.uint8)
    col_score = smooth_1d(light.mean(axis=0), 41)
    intervals = intervals_from_mask(col_score > 0.30, min_width=max(300, int(w * 0.30)))
    if not intervals:
        bx, _by, bw, _bh = find_light_chart_bounds(chart_rgb)
        return bx, bx + bw

    x0 = min(item[0] for item in intervals)
    x1 = max(item[1] for item in intervals) + 1
    return x0, x1


def detect_arrow_in_side(chart_rgb: np.ndarray, side: str) -> Tuple[int, int, int, int, float] | None:
    img8 = as_uint8_rgb(chart_rgb)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape[:2]
    bx, by, bw_chart, bh_chart = find_light_chart_bounds(chart_rgb)

    if side == "left":
        x0, x1 = bx, min(w, bx + int(bw_chart * 0.14))
    else:
        x0, x1 = max(0, bx + int(bw_chart * 0.86)), min(w, bx + bw_chart)
    y0, y1 = by, min(h, by + int(bh_chart * 0.55))

    roi = gray[y0:y1, x0:x1]
    dark = (roi < 95).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: List[Tuple[float, Tuple[int, int, int, int, float]]] = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 180:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 12 or bh < 32:
            continue
        aspect = bh / float(bw)
        fill = area / float(bw * bh)
        if aspect < 1.05 or not 0.10 <= fill <= 0.88:
            continue

        full_x = x0 + x
        full_y = y0 + y
        if side == "left" and full_x > bx + bw_chart * 0.10:
            continue
        if side == "right" and full_x + bw < bx + bw_chart * 0.90:
            continue

        top_bonus = 3.0 if full_y < by + bh_chart * 0.25 else 1.0
        side_bonus = 1.15 if (side == "left" and full_x < bx + bw_chart * 0.06) or (side == "right" and full_x > bx + bw_chart * 0.92) else 1.0
        score = area * aspect * top_bonus * side_bonus
        candidates.append((score, (full_x, full_y, bw, bh, score)))

    if not candidates:
        y_proj0 = int(bh_chart * 0.08)
        y_proj1 = min(dark.shape[0], int(bh_chart * 0.48))
        proj_mask = dark[y_proj0:y_proj1].copy()
        col_score = smooth_1d(proj_mask.mean(axis=0), 7)
        active = col_score > 18.0
        intervals = intervals_from_mask(active, min_width=8)
        projection_candidates: List[Tuple[float, Tuple[int, int, int, int, float]]] = []
        for px0, px1 in intervals:
            if side == "left" and x0 + px0 > bx + bw_chart * 0.09:
                continue
            if side == "right" and x0 + px1 < bx + bw_chart * 0.91:
                continue
            patch = proj_mask[:, px0:px1 + 1]
            ys, xs = np.where(patch > 0)
            if len(xs) == 0:
                continue
            bx0 = x0 + px0 + int(xs.min())
            bx1 = x0 + px0 + int(xs.max())
            by0 = y0 + y_proj0 + int(ys.min())
            by1 = y0 + y_proj0 + int(ys.max())
            bw = bx1 - bx0 + 1
            bh = by1 - by0 + 1
            if bw < 8 or bw > w * 0.08 or bh < 28 or bh > h * 0.42:
                continue
            aspect = bh / float(bw)
            if aspect < 1.0:
                continue
            score = float(patch.sum()) * aspect
            projection_candidates.append((score, (bx0, by0, bw, bh, score)))
        if not projection_candidates:
            return None
        return max(projection_candidates, key=lambda item: item[0])[1]
    return max(candidates, key=lambda item: item[0])[1]


def detect_chart_arrows(chart_rgb: np.ndarray) -> ChartAnchors | None:
    left = detect_arrow_in_side(chart_rgb, "left")
    right = detect_arrow_in_side(chart_rgb, "right")
    if left is None or right is None:
        return None

    h, w = chart_rgb.shape[:2]
    lx, ly, lw, lh, left_score = left
    rx, ry, rw, rh, right_score = right
    left_center = (lx + lw / 2.0, ly + lh / 2.0)
    right_center = (rx + rw / 2.0, ry + rh / 2.0)

    if right_center[0] - left_center[0] < w * 0.75:
        return None
    if abs(right_center[1] - left_center[1]) > h * 0.28:
        return None

    confidence = float(min(left_score, right_score) / max(w * h, 1))
    return ChartAnchors((lx, ly, lw, lh), (rx, ry, rw, rh), confidence)


def find_chart_corners_from_bright_band(gray: np.ndarray) -> np.ndarray | None:
    """
    Fallback para casos en los que la pagina y la carta quedan conectadas en el
    umbral binario. Busca una banda brillante inferior, estrecha y alargada.
    """
    h, w = gray.shape[:2]
    bright = (gray > 120).astype(np.uint8)
    row_score = bright.mean(axis=1)
    active_rows = row_score > 0.20
    min_band_h = max(40, int(h * 0.012))
    row_intervals = intervals_from_mask(active_rows, min_width=min_band_h)

    candidates = []
    for y0, y1 in row_intervals:
        band_h = y1 - y0 + 1
        if y1 < h * 0.55:
            continue
        if float(row_score[y0:y1 + 1].mean()) > 0.75:
            continue

        pad_y = max(12, int(band_h * 0.12))
        by0 = max(0, y0 - pad_y)
        by1 = min(h - 1, y1 + pad_y)
        band = (bright[by0:by1 + 1] * 255).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 15))
        band = cv2.morphologyEx(band, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 10000:
                continue
            rect = cv2.minAreaRect(cnt)
            (_, _), (rw, rh), _angle = rect
            if rw < rh:
                rw, rh = rh, rw
            aspect = rw / rh if rh else 0.0
            x, y, bw, bh = cv2.boundingRect(cnt)
            if 5.0 <= aspect <= 13.5 and bw >= 700 and bh >= 70:
                candidates.append((area, by0, rect))

    if not candidates:
        return None

    _area, by0, rect = max(candidates, key=lambda item: item[0])
    box = cv2.boxPoints(rect)
    box[:, 1] += by0
    return order_points_clockwise(box.astype(np.float32))


# ============================================================
# Detección automática de la carta TE263
# ============================================================

def find_and_warp_chart(img_rgb: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    h, w = img_rgb.shape[:2]
    img8 = as_uint8_rgb(img_rgb)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)

    # La carta suele estar en la parte inferior del escaneo.
    y_start = int(h * 0.55)
    roi = gray[y_start:h, :]

    # Detectar la zona clara de la carta sobre el fondo oscuro.
    _, th = cv2.threshold(roi, 120, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 15))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: List[Tuple[float, np.ndarray]] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 10000:
            continue
        rect = cv2.minAreaRect(cnt)
        (_, _), (rw, rh), _angle = rect
        if rw < rh:
            rw, rh = rh, rw
        aspect = rw / rh if rh else 0.0
        x, y, bw, bh = cv2.boundingRect(cnt)
        if not (5.0 <= aspect <= 13.5 and bw >= 700 and bh >= 70):
            continue

        box = cv2.boxPoints(rect)
        box[:, 1] += y_start
        corners_candidate = order_points_clockwise(box.astype(np.float32))
        chart_candidate = level_chart_by_bottom_edge(warp_chart_from_corners(img_rgb, corners_candidate))
        anchors = detect_chart_arrows(chart_candidate)

        center_x = x + bw / 2.0
        lower_bonus = 1.0 + min(0.35, ((y_start + y + bh / 2.0) / h - 0.55))
        position_bonus = 1.15 if center_x > w * 0.42 else 1.0
        arrow_bonus = 5.0 if anchors is not None else 1.0
        score = float(area) * lower_bonus * position_bonus * arrow_bonus
        candidates.append((score, corners_candidate))

    if candidates:
        corners = max(candidates, key=lambda item: item[0])[1]
    else:
        corners = find_chart_corners_from_bright_band(gray)
        if corners is None:
            raise RuntimeError(
                "No se detectó automáticamente la carta TE263. "
                "Asegúrate de que esté completa y visible."
            )

    # Vista canónica. Mantener estable porque los cálculos de ROIs trabajan sobre esta vista.
    chart = level_chart_by_bottom_edge(warp_chart_from_corners(img_rgb, corners))
    if detect_chart_arrows(chart) is None:
        raise RuntimeError(
            "Se encontró una banda compatible con la TE263, pero no se reconocieron las dos flechas extremas."
        )
    return chart, corners


def find_inner_chart_box(chart_rgb: np.ndarray) -> Tuple[int, int, int, int]:
    """Encuentra la zona interior clara de la carta dentro de la imagen rectificada."""
    img8 = (chart_rgb / 257).astype(np.uint8) if chart_rgb.dtype == np.uint16 else chart_rgb
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)
    mask = (gray > 145).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (51, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > chart_rgb.shape[1] * 0.60 and h > chart_rgb.shape[0] * 0.45:
            boxes.append((cv2.contourArea(c), x, y, w, h))
    if not boxes:
        return 0, 0, chart_rgb.shape[1], chart_rgb.shape[0]
    _, x, y, w, h = max(boxes, key=lambda t: t[0])
    return x, y, w, h


def detect_patch_band(inner_rgb: np.ndarray) -> Tuple[int, int]:
    """Detecta verticalmente la banda donde están los parches."""
    img8 = (inner_rgb / 257).astype(np.uint8) if inner_rgb.dtype == np.uint16 else inner_rgb
    hsv = cv2.cvtColor(img8, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(img8, cv2.COLOR_RGB2GRAY)

    # Saturación o oscuridad: parches + texto/regla. Luego se busca el pico en la zona esperada.
    candidate = ((gray < 190) | (hsv[:, :, 1] > 30)).astype(np.uint8)
    h = candidate.shape[0]
    y_min = int(h * 0.25)
    y_max = int(h * 0.65)
    scores = candidate.sum(axis=1).astype(np.float32)
    scores[:y_min] = 0
    scores[y_max:] = 0
    scores = smooth_1d(scores, 13)

    center = int(np.argmax(scores))
    band_h = max(34, int(h * 0.19))
    y0 = max(0, center - band_h // 2)
    y1 = min(h - 1, center + band_h // 2)
    return y0, y1


def detect_patch_group_edges(inner_rgb: np.ndarray, y0: int, y1: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Detecta el inicio/fin horizontal de los grupos de parches izquierdo y derecho."""
    img8 = (inner_rgb / 257).astype(np.uint8) if inner_rgb.dtype == np.uint16 else inner_rgb
    band = img8[y0:y1 + 1]
    hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)

    # Candidato por columna: oscuro o saturado dentro de la banda de parches.
    candidate = ((gray < 185) | (hsv[:, :, 1] > 30)).astype(np.uint8)
    col_score = candidate.mean(axis=0)
    col_score = smooth_1d(col_score, 9)
    active = col_score > 0.35
    intervals = intervals_from_mask(active, min_width=8)

    w = inner_rgb.shape[1]

    # Grupo izquierdo: una banda ancha, casi continua, en el primer 45% de la carta.
    left_candidates = [iv for iv in intervals if iv[0] < w * 0.46 and (iv[1] - iv[0]) > w * 0.20]
    if left_candidates:
        left = max(left_candidates, key=lambda iv: iv[1] - iv[0])
    else:
        # Fallback calibrado para TE263 en vista canónica.
        left = (int(w * 0.041), int(w * 0.413))

    # Grupo derecho: parches claros separados; se toman varios intervalos en la zona derecha.
    right_intervals = [
        iv for iv in intervals
        if iv[0] > w * 0.56 and iv[0] < w * 0.97 and iv[1] < w * 0.970
    ]
    # Excluir elementos muy anchos del patrón central/resolución si aparecen.
    right_intervals = [iv for iv in right_intervals if (iv[1] - iv[0]) < w * 0.18]

    if len(right_intervals) >= 3:
        r0 = min(iv[0] for iv in right_intervals)
        r1 = max(iv[1] for iv in right_intervals)
        right = (r0, r1)
    else:
        right = (int(w * 0.566), int(w * 0.963))

    # Pequeño saneamiento: asegurar anchuras razonables.
    if (left[1] - left[0]) < w * 0.25:
        left = (int(w * 0.041), int(w * 0.413))
    if (right[1] - right[0]) < w * 0.28:
        right = (int(w * 0.566), int(w * 0.963))

    return left, right


def template_patch_x_positions(chart_left: float, chart_width: float) -> Dict[str, Tuple[float, float]]:
    """
    Posiciones horizontales de medicion en la carta rectificada.

    La plantilla usa las relaciones medidas sobre LT=2345 px:
    P1=100, C1..11=890, P2=1362 y 10..B9=880.
    """
    scale = float(chart_width) / PATCH_TEMPLATE_LT
    left_start = chart_left + PATCH_TEMPLATE_P1 * scale
    left_patch_w = PATCH_TEMPLATE_LEFT_GROUP_WIDTH * scale / len(LEFT_LABELS)
    right_start = chart_left + PATCH_TEMPLATE_P2 * scale
    right_patch_w = PATCH_TEMPLATE_RIGHT_GROUP_WIDTH * scale / len(RIGHT_LABELS)

    positions: Dict[str, Tuple[float, float]] = {}
    for i, label in enumerate(LEFT_LABELS):
        x0 = left_start + i * left_patch_w
        positions[label] = (x0, x0 + left_patch_w)
    for i, label in enumerate(RIGHT_LABELS):
        x0 = right_start + i * right_patch_w
        positions[label] = (x0, x0 + right_patch_w)
    return positions


def generate_patch_rois_auto(chart_rgb: np.ndarray) -> Dict[str, Tuple[float, float, float, float]]:
    """
    Calcula ROIs normalizadas de los 26 parches. No usa posiciones fijas crudas;
    primero detecta la banda vertical de parches y mide la longitud real de la
    carta sobre el borde inferior para escalar las posiciones horizontales.
    """
    chart_h, chart_w = chart_rgb.shape[:2]
    ix, iy, iw, ih = find_inner_chart_box(chart_rgb)
    inner = chart_rgb[iy:iy + ih, ix:ix + iw]

    py0, py1 = detect_patch_band(inner)
    chart_x0, chart_x1 = find_bottom_chart_span(chart_rgb)
    patch_x_positions = template_patch_x_positions(chart_x0, chart_x1 - chart_x0)

    # Las mediciones usan solo el centro del parche, lejos de bordes, texto y sombras.
    rois: Dict[str, Tuple[float, float, float, float]] = {}

    y_margin = 0.22 * (py1 - py0 + 1)
    yy0_full = iy + py0 + y_margin
    yy1_full = iy + py1 - y_margin
    y_center = (yy0_full + yy1_full) / 2.0 + PATCH_SAMPLE_Y_OFFSET
    sample_h = (yy1_full - yy0_full) * PATCH_SAMPLE_FRACTION_Y
    yy0 = y_center - sample_h / 2.0
    yy1 = y_center + sample_h / 2.0
    for label in ALL_LABELS:
        xx0_full, xx1_full = patch_x_positions[label]
        x_center = (xx0_full + xx1_full) / 2.0
        sample_w = (xx1_full - xx0_full) * PATCH_SAMPLE_FRACTION_X
        xx0 = x_center - sample_w / 2.0
        xx1 = x_center + sample_w / 2.0
        rois[label] = (
            max(0.0, xx0 / chart_w),
            max(0.0, yy0 / chart_h),
            min(1.0, xx1 / chart_w),
            min(1.0, yy1 / chart_h),
        )
    return rois


# ============================================================
# Muestreo y reportes
# ============================================================

def sample_patch_values(chart_rgb: np.ndarray, rois: Dict[str, Tuple[float, float, float, float]]) -> Dict[str, np.ndarray]:
    maxv = 65535.0 if chart_rgb.dtype == np.uint16 else 255.0
    chart = chart_rgb.astype(np.float32) / maxv
    h, w = chart.shape[:2]
    values: Dict[str, np.ndarray] = {}

    for label, (x0, y0, x1, y1) in rois.items():
        ix0, iy0 = int(round(x0 * w)), int(round(y0 * h))
        ix1, iy1 = int(round(x1 * w)), int(round(y1 * h))
        ix0, iy0 = max(0, ix0), max(0, iy0)
        ix1, iy1 = min(w, ix1), min(h, iy1)
        patch = chart[iy0:iy1, ix0:ix1, :]
        if patch.size == 0:
            raise RuntimeError(f"ROI vacía para el parche {label}")
        # Mediana: más resistente a polvo, rayas y bordes.
        values[label] = np.median(patch.reshape(-1, 3), axis=0)
    return values


def save_debug_chart(chart_rgb: np.ndarray, rois: Dict[str, Tuple[float, float, float, float]], path: Path) -> None:
    chart8 = (chart_rgb / 257).astype(np.uint8) if chart_rgb.dtype == np.uint16 else chart_rgb.copy()
    dbg = chart8.copy()
    h, w = dbg.shape[:2]
    for label, (x0, y0, x1, y1) in rois.items():
        p1 = int(round(x0 * w)), int(round(y0 * h))
        p2 = int(round(x1 * w)), int(round(y1 * h))
        cv2.rectangle(dbg, p1, p2, (255, 0, 0), 2)
        cv2.putText(dbg, label, (p1[0], max(12, p1[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 0), 1)
    Image.fromarray(dbg).save(path, quality=95)


def save_patch_report(measured_before: Dict[str, np.ndarray], measured_after: Dict[str, np.ndarray] | None, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "patch",
            "before_R", "before_G", "before_B",
            "after_R", "after_G", "after_B",
            "target_R", "target_G", "target_B",
            "L*", "a*", "b*",
        ])
        for label in ALL_LABELS:
            L, a, b = REFERENCE_LAB[label]
            target = lab_to_srgb(L, a, b)
            before = measured_before[label]
            after = measured_after[label] if measured_after is not None else np.array([np.nan, np.nan, np.nan])
            writer.writerow([
                label,
                f"{before[0]:.6f}", f"{before[1]:.6f}", f"{before[2]:.6f}",
                f"{after[0]:.6f}", f"{after[1]:.6f}", f"{after[2]:.6f}",
                f"{target[0]:.6f}", f"{target[1]:.6f}", f"{target[2]:.6f}",
                f"{L:.2f}", f"{a:.2f}", f"{b:.2f}",
            ])


# ============================================================
# Métodos de corrección
# ============================================================

def build_matrix3_correction(measured: Dict[str, np.ndarray], labels: Iterable[str] = ALL_LABELS) -> np.ndarray:
    """
    Matriz 3x3 sin término constante.
    Importante: al no usar offset, el negro permanece negro y se evita que los
    grises oscuros se recorten artificialmente a RGB 0,0,0.
    """
    src = np.array([measured[label] for label in labels], dtype=np.float32)
    dst = np.array([lab_to_srgb(*REFERENCE_LAB[label]) for label in labels], dtype=np.float32)
    src_lin = srgb_to_linear(src)
    dst_lin = srgb_to_linear(dst)
    M, *_ = np.linalg.lstsq(src_lin, dst_lin, rcond=None)
    return M.astype(np.float32)  # forma 3x3


def apply_matrix3_correction(img_rgb: np.ndarray, M: np.ndarray, strength: float = 1.0, chunk_rows: int = 256) -> np.ndarray:
    maxv = 65535.0 if img_rgb.dtype == np.uint16 else 255.0
    out = np.empty_like(img_rgb)

    for y0 in range(0, img_rgb.shape[0], chunk_rows):
        src_block = img_rgb[y0:y0 + chunk_rows].astype(np.float32) / maxv
        lin = srgb_to_linear(src_block)
        flat = lin.reshape(-1, 3)
        corrected = linear_to_srgb(flat @ M).reshape(src_block.shape)
        if strength < 1.0:
            corrected = src_block * (1.0 - strength) + corrected * strength
        out[y0:y0 + chunk_rows] = np.clip(corrected * maxv + 0.5, 0, maxv).astype(img_rgb.dtype)
    return out


def build_neutral_luts(measured: Dict[str, np.ndarray], bitdepth: int) -> List[np.ndarray]:
    max_i = 65535 if bitdepth == 16 else 255
    target_values = np.array([float(np.mean(lab_to_srgb(*REFERENCE_LAB[label]))) for label in NEUTRAL_LABELS], dtype=np.float32)
    luts: List[np.ndarray] = []

    for channel in range(3):
        x = np.array([measured[label][channel] for label in NEUTRAL_LABELS], dtype=np.float32)
        y = target_values.copy()
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        # Anclas fuertes para evitar clipping de sombras y altas luces.
        x = np.concatenate([[0.0], x, [1.0]])
        y = np.concatenate([[0.0], y, [1.0]])

        # Eliminar duplicados de x promediando y.
        xu, yu = [], []
        for value in np.unique(x):
            idx = np.where(x == value)[0]
            xu.append(float(value))
            yu.append(float(np.mean(y[idx])))

        xi = np.linspace(0, 1, max_i + 1, dtype=np.float32)
        lut = np.interp(xi, np.array(xu, dtype=np.float32), np.array(yu, dtype=np.float32))
        lut = np.clip(lut * max_i + 0.5, 0, max_i).astype(np.uint16 if bitdepth == 16 else np.uint8)
        luts.append(lut)
    return luts


def apply_neutral_correction(img_rgb: np.ndarray, luts: List[np.ndarray], strength: float = 1.0) -> np.ndarray:
    if img_rgb.dtype == np.uint8:
        corrected = np.empty_like(img_rgb)
        for c in range(3):
            corrected[:, :, c] = cv2.LUT(img_rgb[:, :, c], luts[c].astype(np.uint8))
    else:
        corrected = np.stack([luts[c][img_rgb[:, :, c]] for c in range(3)], axis=2).astype(np.uint16)

    if strength < 1.0:
        maxv = 65535.0 if img_rgb.dtype == np.uint16 else 255.0
        blended = img_rgb.astype(np.float32) * (1.0 - strength) + corrected.astype(np.float32) * strength
        corrected = np.clip(blended + 0.5, 0, maxv).astype(img_rgb.dtype)
    return corrected


def correct_chart_preview(chart: np.ndarray, rois: Dict[str, Tuple[float, float, float, float]], mode: str, strength: float) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Corrige solo la carta para medir después y generar reportes."""
    measured = sample_patch_values(chart, rois)
    bitdepth = 16 if chart.dtype == np.uint16 else 8

    if mode == "matrix":
        M = build_matrix3_correction(measured)
        cchart = apply_matrix3_correction(chart, M, strength=strength)
    elif mode == "neutral":
        luts = build_neutral_luts(measured, bitdepth=bitdepth)
        cchart = apply_neutral_correction(chart, luts, strength=strength)
    elif mode == "hybrid":
        M = build_matrix3_correction(measured)
        chart_m = apply_matrix3_correction(chart, M, strength=1.0)
        measured_m = sample_patch_values(chart_m, rois)
        luts = build_neutral_luts(measured_m, bitdepth=bitdepth)
        cchart_full = apply_neutral_correction(chart_m, luts, strength=1.0)
        if strength < 1.0:
            maxv = 65535.0 if chart.dtype == np.uint16 else 255.0
            cchart = np.clip(chart.astype(np.float32) * (1.0 - strength) + cchart_full.astype(np.float32) * strength + 0.5, 0, maxv).astype(chart.dtype)
        else:
            cchart = cchart_full
    else:
        raise RuntimeError(f"Modo desconocido: {mode}")

    return cchart, sample_patch_values(cchart, rois)


# ============================================================
# Procesamiento
# ============================================================

def process_one(
    input_path: Path,
    output_path: Path,
    mode: str,
    strength: float,
    debug: bool,
    debug_dir: Path | None = None,
    icc_profile_path: Path | None = DEFAULT_ADOBE_RGB_PROFILE,
) -> None:
    dpi = get_dpi(input_path)
    img = read_rgb_image(input_path)
    img, dpi = normalize_image_to_dpi(img, dpi)
    chart, _corners = find_and_warp_chart(img)
    rois = generate_patch_rois_auto(chart)
    measured_before = sample_patch_values(chart, rois)

    bitdepth = 16 if img.dtype == np.uint16 else 8

    if mode == "matrix":
        M = build_matrix3_correction(measured_before)
        corrected = apply_matrix3_correction(img, M, strength=strength)
        corrected_chart, measured_after = correct_chart_preview(chart, rois, mode, strength)
    elif mode == "neutral":
        luts = build_neutral_luts(measured_before, bitdepth=bitdepth)
        corrected = apply_neutral_correction(img, luts, strength=strength)
        corrected_chart, measured_after = correct_chart_preview(chart, rois, mode, strength)
    elif mode == "hybrid":
        # 1) Corrección cromática sin offset.
        M = build_matrix3_correction(measured_before)
        img_m = apply_matrix3_correction(img, M, strength=1.0)
        chart_m = apply_matrix3_correction(chart, M, strength=1.0)
        measured_m = sample_patch_values(chart_m, rois)
        # 2) Curvas neutrales medidas después de la matriz.
        luts = build_neutral_luts(measured_m, bitdepth=bitdepth)
        corrected_full = apply_neutral_correction(img_m, luts, strength=1.0)
        corrected_chart_full = apply_neutral_correction(chart_m, luts, strength=1.0)
        if strength < 1.0:
            maxv = 65535.0 if img.dtype == np.uint16 else 255.0
            corrected = np.clip(img.astype(np.float32) * (1.0 - strength) + corrected_full.astype(np.float32) * strength + 0.5, 0, maxv).astype(img.dtype)
            corrected_chart = np.clip(chart.astype(np.float32) * (1.0 - strength) + corrected_chart_full.astype(np.float32) * strength + 0.5, 0, maxv).astype(chart.dtype)
        else:
            corrected = corrected_full
            corrected_chart = corrected_chart_full
        measured_after = sample_patch_values(corrected_chart, rois)
    else:
        raise RuntimeError(f"Modo desconocido: {mode}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_tiff_uncompressed(output_path, corrected, TARGET_DPI, icc_profile_path)
    copy_source_metadata(input_path, output_path)

    if debug:
        debug_base = debug_dir if debug_dir is not None else output_path.parent
        debug_base.mkdir(parents=True, exist_ok=True)
        save_debug_chart(chart, rois, debug_base / f"{output_path.stem}_debug_chart_before.jpg")
        save_debug_chart(corrected_chart, rois, debug_base / f"{output_path.stem}_debug_chart_after.jpg")
        save_patch_report(measured_before, measured_after, debug_base / f"{output_path.stem}_patch_report.csv")

    print(f"OK: {input_path.name} -> {output_path}")


def iter_images(folder: Path, recursive: bool) -> Iterable[Path]:
    paths = folder.rglob("*") if recursive else folder.glob("*")
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Corrección de color con carta Image Engineering TE263")
    parser.add_argument("input", type=Path, help="Imagen o carpeta de entrada")
    parser.add_argument("output", type=Path, nargs="?", help="Archivo TIFF de salida o carpeta de salida")
    parser.add_argument(
        "--mode",
        choices=["hybrid", "matrix", "neutral"],
        default="hybrid",
        help="hybrid = recomendado; matrix = matriz 3x3 sin offset; neutral = solo escala de grises",
    )
    parser.add_argument("--strength", type=float, default=1.0, help="Intensidad de corrección: 0.0 a 1.0")
    parser.add_argument("--debug", action="store_true", help="Guardar carta detectada con ROIs y CSV de mediciones")
    parser.add_argument("--debug-dir", type=Path, help="Carpeta separada para JPG de debug y CSV de mediciones")
    parser.add_argument(
        "--icc-profile",
        type=Path,
        default=DEFAULT_ADOBE_RGB_PROFILE,
        help="Perfil ICC a incrustar en los TIFF de salida. Por defecto: AdobeRGB1998.icc de Windows",
    )
    parser.add_argument("--recursive", action="store_true", help="Procesar subcarpetas si la entrada es una carpeta")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Si se procesa una carpeta, continuar con el resto de imagenes cuando una falle",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"No existe la entrada: {args.input}")

    strength = max(0.0, min(1.0, args.strength))

    if args.input.is_dir():
        if args.output is None:
            raise SystemExit("Cuando la entrada es una carpeta, debes indicar una carpeta de salida.")
        if args.output.exists() and not args.output.is_dir():
            raise SystemExit(f"La salida debe ser una carpeta, pero ya existe como archivo: {args.output}")
        args.output.mkdir(parents=True, exist_ok=True)
        if args.debug and args.debug_dir is not None:
            args.debug_dir.mkdir(parents=True, exist_ok=True)
        images = list(iter_images(args.input, args.recursive))
        if not images:
            scope = "recursivamente" if args.recursive else "en el nivel principal"
            extensions = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise SystemExit(f"No se encontraron imagenes {scope} en {args.input} ({extensions}).")

        failures: List[Tuple[Path, Exception]] = []
        success_count = 0

        for img_path in images:
            rel = img_path.relative_to(args.input)
            out_path = args.output / rel.with_suffix(".tif")
            image_debug_dir = (args.debug_dir / rel.parent) if args.debug_dir is not None else None
            try:
                process_one(
                    img_path,
                    out_path,
                    args.mode,
                    strength,
                    args.debug,
                    debug_dir=image_debug_dir,
                    icc_profile_path=args.icc_profile,
                )
                success_count += 1
            except Exception as exc:
                if not args.continue_on_error:
                    raise
                failures.append((img_path, exc))
                print(f"ERROR: {img_path.name}: {exc}")

        if failures:
            print(f"Procesadas correctamente: {success_count}/{len(images)}. Errores: {len(failures)}.")
            for img_path, exc in failures:
                print(f"ERROR_RESUMEN: {img_path}: {exc}")
            raise SystemExit(1)
        print(f"Procesadas correctamente: {success_count}/{len(images)}.")
    else:
        output_path = args.output or args.input.with_name(args.input.stem + "_corrected.tif")
        if output_path.exists() and output_path.is_dir():
            raise SystemExit(f"La salida debe ser un archivo, pero es una carpeta: {output_path}")
        process_one(
            args.input,
            output_path,
            args.mode,
            strength,
            args.debug,
            debug_dir=args.debug_dir,
            icc_profile_path=args.icc_profile,
        )


if __name__ == "__main__":
    main()
