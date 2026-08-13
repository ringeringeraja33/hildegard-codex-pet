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
        for column in range(7)
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
    assert all(
        ImageChops.difference(atlas_cell(3, column), atlas_cell(4, column)).getbbox()
        is None
        for column in range(8)
    ), "hover row must reuse the grounded wave cycle"

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
        "hoverState": "grounded-wave",
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
