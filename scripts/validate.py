#!/usr/bin/env python3
"""Validate the install-ready Hildegard Codex pet package."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "package" / "pet.json"
ATLAS = ROOT / "package" / "spritesheet.webp"
REPORT = ROOT / "qa" / "validation.json"

EXPECTED_ATLAS_SIZE = (1536, 2288)
EXPECTED_GRID = (8, 11)
EXPECTED_CELL_SIZE = (192, 208)
SOURCE_KEY = (246, 2, 234)
FRINGE_DISTANCE = 92.0
EDGE_RADIUS = 2
ALPHA_MINIMUM = 16


def rgb_diff_bbox(left: Image.Image, right: Image.Image):
    """RGBA difference zeros out shared alpha, so compare flattened RGB."""
    return ImageChops.difference(left.convert("RGB"), right.convert("RGB")).getbbox()


def pixel_data(image: Image.Image):
    return (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )


def chroma_fringe_count(image: Image.Image) -> int:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    visible = [value > 0 for value in pixel_data(alpha)]
    transparent = Image.new("L", alpha.size)
    transparent.putdata([0 if value else 255 for value in visible])
    expanded = transparent.filter(ImageFilter.MaxFilter(EDGE_RADIUS * 2 + 1))
    return sum(
        alpha_value >= ALPHA_MINIMUM
        and near_transparency > 0
        and math.dist(color[:3], SOURCE_KEY) <= FRINGE_DISTANCE
        for color, alpha_value, near_transparency in zip(
            pixel_data(rgba),
            pixel_data(alpha),
            pixel_data(expanded),
        )
    )


def assert_utf8_text(path: Path) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    assert "\ufffd" not in text, f"replacement character in {path}"
    assert "?" * 2 not in text, f"possible encoding replacement in {path}"
    return text


def lower_body_center_x(frame: Image.Image) -> float:
    alpha = frame.getchannel("A")
    bound = alpha.getbbox()
    assert bound is not None, "animation frame is empty"
    lower_top = bound[1] + round((bound[3] - bound[1]) * 0.65)
    lower = alpha.crop((bound[0], lower_top, bound[2], bound[3]))
    weights = list(pixel_data(lower))
    total = sum(weights)
    assert total, "animation frame has no lower-body anchor"
    return bound[0] + sum(
        (index % lower.width) * weight
        for index, weight in enumerate(weights)
    ) / total


def first_visible_row_width(frame: Image.Image) -> int:
    """Return silhouette width where the first visible pixels appear."""
    alpha = frame.getchannel("A")
    bound = alpha.getbbox()
    assert bound is not None, "frame is empty"
    return sum(alpha.getpixel((x, bound[1])) > 0 for x in range(alpha.width))


def main() -> None:
    manifest_text = assert_utf8_text(MANIFEST)
    manifest = json.loads(manifest_text)
    assert manifest["id"] == "hildegard"
    assert manifest["displayName"] == "小希尔德加德"
    assert manifest["spriteVersionNumber"] == 2
    assert manifest["spritesheetPath"] == "spritesheet.webp"

    image = Image.open(ATLAS).convert("RGBA")
    assert image.size == EXPECTED_ATLAS_SIZE, image.size
    assert image.width % EXPECTED_GRID[0] == 0
    assert image.height % EXPECTED_GRID[1] == 0
    assert (
        image.width // EXPECTED_GRID[0],
        image.height // EXPECTED_GRID[1],
    ) == EXPECTED_CELL_SIZE

    rgba_pixels = list(pixel_data(image))
    transparent_rgb_residue = sum(
        alpha == 0 and (red or green or blue)
        for red, green, blue, alpha in rgba_pixels
    )
    assert transparent_rgb_residue == 0, (
        f"transparent RGB residue pixels: {transparent_rgb_residue}"
    )

    visible_pixels = sum(alpha > 0 for _, _, _, alpha in rgba_pixels)
    assert visible_pixels > 250_000, f"unexpected visible coverage: {visible_pixels}"

    def atlas_cell(row: int, column: int) -> Image.Image:
        left = column * EXPECTED_CELL_SIZE[0]
        top = row * EXPECTED_CELL_SIZE[1]
        return image.crop(
            (
                left,
                top,
                left + EXPECTED_CELL_SIZE[0],
                top + EXPECTED_CELL_SIZE[1],
            )
        )

    idle_foot_baselines = [
        atlas_cell(0, column).getchannel("A").getbbox()[3]
        for column in range(6)
    ]
    assert len(set(idle_foot_baselines)) == 1, (
        f"idle baseline jitter: {idle_foot_baselines}"
    )

    wave_foot_baselines = [
        atlas_cell(3, column).getchannel("A").getbbox()[3]
        for column in range(8)
    ]
    assert len(set(wave_foot_baselines)) == 1, (
        f"wave baseline jitter: {wave_foot_baselines}"
    )
    idle_body_centers = [
        lower_body_center_x(atlas_cell(0, column))
        for column in range(6)
    ]
    assert max(idle_body_centers) - min(idle_body_centers) <= 1.0, (
        f"idle horizontal jitter: {idle_body_centers}"
    )
    wave_body_centers = [
        lower_body_center_x(atlas_cell(3, column))
        for column in range(8)
    ]
    assert max(wave_body_centers) - min(wave_body_centers) <= 1.0, (
        f"wave horizontal jitter: {wave_body_centers}"
    )
    wave_face_box = (58, 28, 150, 130)
    wave_face = atlas_cell(3, 0).crop(wave_face_box)
    wave_face_locked = all(
        ImageChops.difference(
            wave_face,
            atlas_cell(3, column).crop(wave_face_box),
        ).getbbox()
        is None
        for column in range(1, 8)
    )
    assert wave_face_locked, "wave animation changes pixels inside the face guard"

    idle_open_frame_columns = (0, 3, 4, 5)
    idle_blink_frame_columns = (1, 2)
    idle_open_frame = atlas_cell(0, idle_open_frame_columns[0])
    idle_blink_frame = atlas_cell(0, idle_blink_frame_columns[0])
    assert all(
        rgb_diff_bbox(idle_open_frame, atlas_cell(0, column)) is None
        for column in idle_open_frame_columns[1:]
    ), "idle open-eye hold frames must be pixel-identical"
    assert all(
        rgb_diff_bbox(idle_blink_frame, atlas_cell(0, column)) is None
        for column in idle_blink_frame_columns[1:]
    ), "idle closed-eye blink frames must be pixel-identical"
    assert rgb_diff_bbox(idle_open_frame, idle_blink_frame) is not None, (
        "idle blink must use the GitHub closed-eye frame, not another open hold"
    )
    idle_head_lock = idle_open_frame.copy()
    idle_blink_lock = idle_blink_frame.copy()
    idle_head_lock.paste((0, 0, 0, 0), (72, 68, 139, 103))
    idle_blink_lock.paste((0, 0, 0, 0), (72, 68, 139, 103))
    assert rgb_diff_bbox(idle_head_lock, idle_blink_lock) is None, (
        "idle blink must not move pixels outside the eyelids"
    )
    assert atlas_cell(0, 6).getchannel("A").getbbox() is None, "idle must use 6 official frames"
    assert atlas_cell(0, 7).getchannel("A").getbbox() is None, "idle must use 6 official frames"

    animated_cells = [
        atlas_cell(row, column)
        for row in (0, 3, 4)
        for column in range(8)
        if atlas_cell(row, column).getchannel("A").getbbox() is not None
    ]
    cell_width, cell_height = EXPECTED_CELL_SIZE
    visible_border_pixels = sum(
        any(
            frame.getchannel("A").getpixel((x, y)) > 0
            for x, y in (
                *((x, 0) for x in range(cell_width)),
                *((x, cell_height - 1) for x in range(cell_width)),
                *((0, y) for y in range(cell_height)),
                *((cell_width - 1, y) for y in range(cell_height)),
            )
        )
        for frame in animated_cells
    )
    assert visible_border_pixels == 0, (
        f"animated cells touch a pixel boundary: {visible_border_pixels}"
    )
    assert all(
        ImageChops.difference(atlas_cell(3, column), atlas_cell(4, column)).getbbox()
        is None
        for column in range(8)
    ), "hover row must reuse the grounded wave cycle"

    reading_top_widths = {
        "working": first_visible_row_width(atlas_cell(7, 0)),
        "review": first_visible_row_width(atlas_cell(8, 0)),
    }
    assert all(width <= 8 for width in reading_top_widths.values()), (
        f"reading-state vision flames are clipped: {reading_top_widths}"
    )

    fringe_pixels = chroma_fringe_count(image)
    assert fringe_pixels == 0, f"source chroma fringe pixels: {fringe_pixels}"

    for path in (
        ROOT / "README.md",
        ROOT / "NOTICE.md",
        ROOT / "source" / "README.md",
        ROOT / "qa" / "asset-prompt.md",
    ):
        assert_utf8_text(path)

    report = {
        "status": "passed",
        "manifestId": manifest["id"],
        "displayName": manifest["displayName"],
        "spriteVersionNumber": manifest["spriteVersionNumber"],
        "atlasSize": list(image.size),
        "grid": list(EXPECTED_GRID),
        "cellSize": list(EXPECTED_CELL_SIZE),
        "visiblePixels": visible_pixels,
        "idleFootBaselines": idle_foot_baselines,
        "waveFootBaselines": wave_foot_baselines,
        "idleBodyCenters": [round(value, 3) for value in idle_body_centers],
        "waveBodyCenters": [round(value, 3) for value in wave_body_centers],
        "waveFacePixelLock": wave_face_locked,
        "idleOpenFrameColumns": list(idle_open_frame_columns),
        "idleBlinkFrameColumns": list(idle_blink_frame_columns),
        "idleOfficialFrameCount": 6,
        "animatedCellsTouchingBounds": visible_border_pixels,
        "hoverState": "grounded-wave",
        "readingStateTopWidths": reading_top_widths,
        "transparentRgbResiduePixels": transparent_rgb_residue,
        "sourceChromaFringePixels": fringe_pixels,
        "utf8Readback": "passed",
    }
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert_utf8_text(REPORT)

    print("Hildegard package validation passed")
    print("atlas=1536×2288 RGBA WebP, grid=8×11, cell=192×208, version=2")
    print("transparent_rgb_residue=0, source_chroma_fringe=0, utf8=passed")


if __name__ == "__main__":
    main()
