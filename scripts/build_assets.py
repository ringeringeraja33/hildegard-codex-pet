#!/usr/bin/env python3
"""Build the Codex v2 atlas and preview assets from the generated pose sheet."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "hildegard-pose-sheet.png"
ATLAS_PATH = ROOT / "package" / "spritesheet.webp"
CONTACT_SHEET_PATH = ROOT / "assets" / "contact-sheet.png"
LOOK_SHEET_PATH = ROOT / "assets" / "look-directions.png"
IDLE_GIF_PATH = ROOT / "assets" / "idle.gif"
BUILD_REPORT_PATH = ROOT / "qa" / "build-report.json"

CELL_WIDTH = 192
CELL_HEIGHT = 208
COLUMNS = 8
ROWS = 11
ATLAS_SIZE = (CELL_WIDTH * COLUMNS, CELL_HEIGHT * ROWS)

ROW_LABELS = (
    "row 0 · idle",
    "row 1 · running-right",
    "row 2 · running-left",
    "row 3 · waving",
    "row 4 · jumping",
    "row 5 · failed",
    "row 6 · waiting",
    "row 7 · working",
    "row 8 · review",
    "row 9 · look 000–157.5",
    "row 10 · look 180–337.5",
)

ACTIVE_FRAMES = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)


def remove_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = []
    for red, green, blue, alpha in rgba.getdata():
        if alpha == 0:
            pixels.append((0, 0, 0, 0))
        else:
            pixels.append((red, green, blue, alpha))
    rgba.putdata(pixels)
    return rgba


def extract_poses(sheet: Image.Image) -> list[Image.Image]:
    if sheet.width % 3 or sheet.height % 3:
        raise ValueError(f"pose sheet must divide into 3×3 cells: {sheet.size}")

    source_cell_width = sheet.width // 3
    source_cell_height = sheet.height // 3
    poses: list[Image.Image] = []
    for row in range(3):
        for column in range(3):
            cell = sheet.crop(
                (
                    column * source_cell_width,
                    row * source_cell_height,
                    (column + 1) * source_cell_width,
                    (row + 1) * source_cell_height,
                )
            )
            alpha = cell.getchannel("A")
            bbox = alpha.getbbox()
            if bbox is None:
                raise ValueError(f"pose {len(poses)} has no visible pixels")
            poses.append(cell.crop(bbox))
    return poses


def render_pose(
    pose: Image.Image,
    *,
    max_width: int = 178,
    max_height: int = 198,
    scale_delta: float = 0.0,
    angle: float = 0.0,
    dx: int = 0,
    dy: int = 0,
    flip: bool = False,
    foot_y: int = 204,
) -> Image.Image:
    subject = ImageOps.mirror(pose) if flip else pose.copy()
    base_scale = min(max_width / subject.width, max_height / subject.height)
    scale = max(0.1, base_scale * (1.0 + scale_delta))
    size = (
        max(1, round(subject.width * scale)),
        max(1, round(subject.height * scale)),
    )
    subject = subject.resize(size, Image.Resampling.LANCZOS)
    if angle:
        subject = subject.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            center=(subject.width / 2, subject.height * 0.72),
        )

    frame = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    requested_x = (CELL_WIDTH - subject.width) // 2 + dx
    requested_y = foot_y - subject.height + dy
    # Motion offsets must never push pixels outside a fixed atlas cell. Codex
    # clips each cell before displaying it, so clamp the composed subject while
    # preserving as much of the requested movement as the transparent margin allows.
    x = min(max(requested_x, 0), max(0, CELL_WIDTH - subject.width))
    y = min(max(requested_y, 0), max(0, CELL_HEIGHT - subject.height))
    frame.alpha_composite(subject, (x, y))
    return remove_transparent_rgb(frame)


def make_rows(poses: list[Image.Image]) -> list[list[Image.Image]]:
    transparent = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    rows: list[list[Image.Image]] = []

    idle_motion = (
        (0.000, 0),
        (0.008, -1),
        (0.014, -2),
        (0.008, -1),
        (0.000, 0),
        (-0.004, 0),
        (0.000, 0),
    )
    idle = [render_pose(poses[0], scale_delta=scale, dy=dy) for scale, dy in idle_motion]
    rows.append(idle + [transparent.copy()])

    run_motion = ((-3, 0, -2.0), (-1, -3, -1.0), (1, -5, 0.0), (3, -2, 1.0), (3, 0, 2.0), (1, -3, 1.0), (-1, -5, 0.0), (-3, -2, -1.0))
    rows.append([render_pose(poses[1], dx=dx, dy=dy, angle=angle, max_width=184) for dx, dy, angle in run_motion])
    rows.append([render_pose(poses[1], dx=-dx, dy=dy, angle=-angle, flip=True, max_width=184) for dx, dy, angle in run_motion])

    wave = [render_pose(poses[3], angle=angle, dy=dy) for angle, dy in ((-1.0, 0), (1.5, -1), (-1.5, 0), (1.0, -1))]
    rows.append(wave + [transparent.copy() for _ in range(4)])

    jump = [render_pose(poses[4], dy=dy, angle=angle, max_width=184) for dy, angle in ((0, -1.0), (-17, -2.0), (-34, 0.0), (-17, 2.0), (0, 1.0))]
    rows.append(jump + [transparent.copy() for _ in range(3)])

    rows.append([render_pose(poses[5], dx=dx, angle=angle) for dx, angle in ((0, 0), (-3, -1.4), (3, 1.4), (-2, -1.0), (2, 1.0), (-1, -0.5), (1, 0.5), (0, 0))])

    waiting = [render_pose(poses[6], scale_delta=scale, dy=dy) for scale, dy in ((0, 0), (0.005, -1), (0.010, -1), (0.005, 0), (0, 0), (-0.003, 0))]
    rows.append(waiting + [transparent.copy() for _ in range(2)])

    working = [render_pose(poses[7], dx=dx, dy=dy, angle=angle, max_width=188, max_height=194) for dx, dy, angle in ((0, 0, 0), (-1, 0, -0.8), (0, -1, 0), (1, 0, 0.8), (0, 0, 0), (-1, -1, -0.5))]
    rows.append(working + [transparent.copy() for _ in range(2)])

    review = [render_pose(poses[8], dx=dx, dy=dy, scale_delta=scale) for dx, dy, scale in ((0, 0, 0), (-1, -1, 0.004), (0, -2, 0.008), (1, -1, 0.004), (0, 0, 0), (0, 0, -0.003))]
    rows.append(review + [transparent.copy() for _ in range(2)])

    upper_look = [render_pose(poses[0], dx=dx, dy=dy, angle=angle) for dx, dy, angle in ((-5, 1, -3.0), (-4, -1, -2.0), (-2, -3, -1.0), (0, -4, 0), (2, -3, 1.0), (4, -1, 2.0), (5, 1, 3.0), (3, 2, 2.0))]
    rows.append(upper_look)

    lower_look = [render_pose(poses[0], dx=dx, dy=dy, angle=angle) for dx, dy, angle in ((3, 3, 2.0), (1, 4, 1.0), (-1, 4, 0), (-3, 3, -1.0), (-5, 2, -3.0), (-4, 0, -2.0), (-2, -2, -1.0), (1, -2, 1.0))]
    rows.append(lower_look)

    if len(rows) != ROWS or any(len(row) != COLUMNS for row in rows):
        raise AssertionError("atlas row construction failed")
    return rows


def build_atlas(rows: list[list[Image.Image]]) -> Image.Image:
    atlas = Image.new("RGBA", ATLAS_SIZE, (0, 0, 0, 0))
    for row_index, row in enumerate(rows):
        for column_index, frame in enumerate(row):
            atlas.alpha_composite(frame, (column_index * CELL_WIDTH, row_index * CELL_HEIGHT))
    return remove_transparent_rgb(atlas)


def checkerboard(size: tuple[int, int], block: int = 12) -> Image.Image:
    board = Image.new("RGB", size, "#f3f1eb")
    draw = ImageDraw.Draw(board)
    for y in range(0, size[1], block):
        for x in range(0, size[0], block):
            if (x // block + y // block) % 2:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill="#ddd9cf")
    return board


def flatten_preview(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    frame = image.resize(size, Image.Resampling.LANCZOS)
    background = checkerboard(size)
    background.paste(frame, mask=frame.getchannel("A"))
    return background


def build_contact_sheet(rows: list[list[Image.Image]]) -> Image.Image:
    preview_cell = (96, 104)
    label_height = 22
    row_height = preview_cell[1] + label_height
    sheet = Image.new("RGB", (preview_cell[0] * COLUMNS, row_height * ROWS), "#12241e")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for row_index, row in enumerate(rows):
        top = row_index * row_height
        draw.text((6, top + 5), ROW_LABELS[row_index], fill="#f4efe2", font=font)
        count_label = f"{ACTIVE_FRAMES[row_index]} frames"
        label_width = draw.textbbox((0, 0), count_label, font=font)[2]
        draw.text((sheet.width - label_width - 6, top + 5), count_label, fill="#d6c388", font=font)
        for column_index, frame in enumerate(row):
            preview = flatten_preview(frame, preview_cell)
            sheet.paste(preview, (column_index * preview_cell[0], top + label_height))
    return sheet


def build_look_sheet(rows: list[list[Image.Image]]) -> Image.Image:
    sheet = Image.new("RGB", (CELL_WIDTH * COLUMNS, CELL_HEIGHT * 2), "#f3f1eb")
    for row_offset, row in enumerate(rows[9:11]):
        for column_index, frame in enumerate(row):
            background = checkerboard((CELL_WIDTH, CELL_HEIGHT), block=16)
            background.paste(frame, mask=frame.getchannel("A"))
            sheet.paste(background, (column_index * CELL_WIDTH, row_offset * CELL_HEIGHT))
    return sheet


def save_idle_gif(frames: list[Image.Image]) -> None:
    gif_frames: list[Image.Image] = []
    for frame in frames:
        rgba = frame.copy()
        alpha = rgba.getchannel("A")
        palette = rgba.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
        mask = alpha.point(lambda value: 255 if value <= 8 else 0)
        palette.paste(0, mask)
        palette.info["transparency"] = 0
        gif_frames.append(palette)
    gif_frames[0].save(IDLE_GIF_PATH, save_all=True, append_images=gif_frames[1:], duration=(220, 170, 170, 170, 220, 260, 700), loop=0, disposal=2, transparency=0)


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    poses = extract_poses(source)
    rows = make_rows(poses)
    atlas = build_atlas(rows)

    ROOT.joinpath("package").mkdir(exist_ok=True)
    ROOT.joinpath("assets").mkdir(exist_ok=True)
    ROOT.joinpath("qa").mkdir(exist_ok=True)

    atlas.save(ATLAS_PATH, "WEBP", lossless=True, method=6, exact=True)
    build_contact_sheet(rows).save(CONTACT_SHEET_PATH, "PNG", optimize=True)
    build_look_sheet(rows).save(LOOK_SHEET_PATH, "PNG", optimize=True)
    save_idle_gif(rows[0][:7])

    report = {"source": str(SOURCE.relative_to(ROOT)), "sourceSize": list(source.size), "poseCount": len(poses), "atlas": str(ATLAS_PATH.relative_to(ROOT)), "atlasSize": list(atlas.size), "grid": [COLUMNS, ROWS], "cellSize": [CELL_WIDTH, CELL_HEIGHT], "activeFrames": list(ACTIVE_FRAMES)}
    BUILD_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {ATLAS_PATH.relative_to(ROOT)}: {atlas.size[0]}×{atlas.size[1]}")
    print("Generated contact sheet, look-direction sheet, idle GIF and build report")


if __name__ == "__main__":
    main()
