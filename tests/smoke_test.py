from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from te263_color_corrector.calibrator import (  # noqa: E402
    ALL_LABELS,
    LEFT_LABELS,
    PATCH_TEMPLATE_CHART_WIDTH,
    PATCH_TEMPLATE_LEFT_MARGIN,
    PATCH_TEMPLATE_RIGHT_MARGIN,
    PATCH_TEMPLATE_WIDTH,
    REFERENCE_LAB,
    RIGHT_LABELS,
    find_bottom_chart_span,
    iter_images,
    lab_to_srgb,
    process_one,
    template_patch_x_positions,
)


def _rgb8(label: str) -> np.ndarray:
    rgb = lab_to_srgb(*REFERENCE_LAB[label])
    return np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _draw_group(
    image: np.ndarray,
    labels: list[str],
    chart_x: int,
    chart_y: int,
    chart_w: int,
    chart_h: int,
    x0_rel: float,
    x1_rel: float,
) -> None:
    x0 = chart_x + int(round(chart_w * x0_rel))
    x1 = chart_x + int(round(chart_w * x1_rel))
    y0 = chart_y + int(round(chart_h * 0.39))
    y1 = chart_y + int(round(chart_h * 0.58))
    cell_w = (x1 - x0) / len(labels)

    for i, label in enumerate(labels):
        px0 = x0 + int(round(i * cell_w))
        px1 = x0 + int(round((i + 1) * cell_w))
        image[y0:y1, px0:px1] = _rgb8(label)


def _draw_arrow(image: np.ndarray, x: int, y: int, scale: int = 1) -> None:
    shaft_w = 18 * scale
    shaft_h = 58 * scale
    head_w = 50 * scale
    head_h = 38 * scale
    cx = x
    image[y + head_h : y + head_h + shaft_h, cx - shaft_w // 2 : cx + shaft_w // 2] = 0
    points = np.array([
        [cx, y],
        [cx - head_w // 2, y + head_h],
        [cx + head_w // 2, y + head_h],
    ], dtype=np.int32)
    import cv2

    cv2.fillConvexPoly(image, points, (0, 0, 0))


def create_synthetic_input(path: Path) -> None:
    width, height = 3000, 1800
    image = np.full((height, width, 3), 28, dtype=np.uint8)

    chart_x, chart_y = 150, 1120
    chart_w, chart_h = 2700, 335
    image[chart_y : chart_y + chart_h, chart_x : chart_x + chart_w] = 235
    _draw_arrow(image, chart_x + 45, chart_y + 15, scale=1)
    _draw_arrow(image, chart_x + chart_w - 45, chart_y + 15, scale=1)

    left_start = PATCH_TEMPLATE_LEFT_MARGIN / PATCH_TEMPLATE_CHART_WIDTH
    left_end = (PATCH_TEMPLATE_LEFT_MARGIN + len(LEFT_LABELS) * PATCH_TEMPLATE_WIDTH) / PATCH_TEMPLATE_CHART_WIDTH
    right_start = (
        PATCH_TEMPLATE_CHART_WIDTH - PATCH_TEMPLATE_RIGHT_MARGIN - len(RIGHT_LABELS) * PATCH_TEMPLATE_WIDTH
    ) / PATCH_TEMPLATE_CHART_WIDTH
    right_end = (PATCH_TEMPLATE_CHART_WIDTH - PATCH_TEMPLATE_RIGHT_MARGIN) / PATCH_TEMPLATE_CHART_WIDTH
    _draw_group(image, LEFT_LABELS, chart_x, chart_y, chart_w, chart_h, left_start, left_end)
    _draw_group(image, RIGHT_LABELS, chart_x, chart_y, chart_w, chart_h, right_start, right_end)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, compression="tiff_lzw", dpi=(300, 300))


def check_iter_images(run_dir: Path) -> None:
    scan_dir = run_dir / "iter_images"
    scan_dir.mkdir(parents=True, exist_ok=True)
    for name in ["b.JPG", "a.tif", "notes.txt", "nested"]:
        path = scan_dir / name
        if "." in name:
            path.write_bytes(b"x")
        else:
            path.mkdir(exist_ok=True)
    (scan_dir / "nested" / "c.PNG").write_bytes(b"x")

    top_level = [path.name for path in iter_images(scan_dir, recursive=False)]
    recursive = [path.relative_to(scan_dir).as_posix() for path in iter_images(scan_dir, recursive=True)]

    if top_level != ["a.tif", "b.JPG"]:
        raise AssertionError(f"Unexpected top-level images: {top_level}")
    if recursive != ["a.tif", "b.JPG", "nested/c.PNG"]:
        raise AssertionError(f"Unexpected recursive images: {recursive}")


def check_template_patch_positions() -> None:
    positions = template_patch_x_positions(0, 2500)
    if positions["C1"] != (100.0, 170.0):
        raise AssertionError(f"Unexpected C1 position: {positions['C1']}")
    if positions["B1"] != (170.0, 240.0):
        raise AssertionError(f"Unexpected B1 position: {positions['B1']}")
    if positions["B9"] != (2318.0, 2388.0):
        raise AssertionError(f"Unexpected B9 position: {positions['B9']}")


def check_bottom_span_on_synthetic(input_path: Path) -> None:
    from te263_color_corrector.calibrator import find_and_warp_chart, read_rgb_image

    chart, _corners = find_and_warp_chart(read_rgb_image(input_path))
    x0, x1 = find_bottom_chart_span(chart)
    if not (0 <= x0 < 120 and 2380 < x1 <= 2500):
        raise AssertionError(f"Unexpected bottom chart span: {(x0, x1)}")


def main() -> None:
    run_dir = PROJECT_ROOT / "test_runs" / "smoke"
    input_path = run_dir / "synthetic_te263_input.tif"
    output_path = run_dir / "synthetic_te263_output.tif"

    check_iter_images(run_dir)
    check_template_patch_positions()
    create_synthetic_input(input_path)
    check_bottom_span_on_synthetic(input_path)
    process_one(input_path, output_path, mode="hybrid", strength=1.0, debug=True)

    expected = [
        output_path,
        output_path.with_name(output_path.stem + "_debug_chart_before.jpg"),
        output_path.with_name(output_path.stem + "_debug_chart_after.jpg"),
        output_path.with_name(output_path.stem + "_patch_report.csv"),
    ]
    missing = [path for path in expected if not path.exists()]
    if missing:
        raise AssertionError(f"Missing expected outputs: {missing}")

    with output_path.open("rb") as f:
        signature = f.read(4)
    if signature not in (b"II*\x00", b"MM\x00*"):
        raise AssertionError(f"Output is not a TIFF file: {output_path}")

    report_path = output_path.with_name(output_path.stem + "_patch_report.csv")
    with report_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    if len(rows) != len(ALL_LABELS):
        raise AssertionError(f"Expected {len(ALL_LABELS)} report rows, got {len(rows)}")

    print(f"Smoke test OK: {output_path}")
    print(f"Debug report: {report_path}")


if __name__ == "__main__":
    main()
