#!/usr/bin/env python3
"""Build the Codex v2 atlas and preview assets from the generated pose sheet."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "hildegard-pose-sheet.png"
ANIMATION_SOURCE = ROOT / "source" / "hildegard-animation-sheet.png"
ATLAS_PATH = ROOT / "package" / "spritesheet.webp"
CONTACT_SHEET_PATH = ROOT / "assets" / "contact-sheet.png"
LOOK_SHEET_PATH = ROOT / "assets" / "look-directions.png"
IDLE_GIF_PATH = ROOT / "assets" / "idle.gif"
BUILD_REPORT_PATH = ROOT / "qa" / "build-report.json"
WAVE_FACE_LOCK_BOX = (58, 28, 150, 130)
# Official Codex idle uses 6 frames. Blink sits on the two 110ms slots.
IDLE_DURATIONS_MS = (280, 110, 110, 140, 140, 320)
# Atlas-space box covering both eyelids on the GitHub closed-eye frame.
IDLE_EYE_BOX = (78, 74, 132, 96)

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
    "row 4 · hover-wave",
    "row 5 · failed",
    "row 6 · waiting",
    "row 7 · working",
    "row 8 · review",
    "row 9 · look 000–157.5",
    "row 10 · look 180–337.5",
)

ACTIVE_FRAMES = (6, 8, 8, 8, 8, 8, 6, 6, 6, 8, 8)


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


def extract_animation_rows(sheet: Image.Image) -> tuple[list[Image.Image], list[Image.Image]]:
    """Extract and anchor wave and idle frames from the 4×2 source sheet."""
    if sheet.width % 4 or sheet.height % 2:
        raise ValueError(f"animation sheet must divide into 4×2 cells: {sheet.size}")

    cell_width = sheet.width // 4
    cell_height = sheet.height // 2
    rows: list[list[Image.Image]] = []
    for row in range(2):
        cells = [
            sheet.crop(
                (
                    column * cell_width,
                    row * cell_height,
                    (column + 1) * cell_width,
                    (row + 1) * cell_height,
                )
            )
            for column in range(4)
        ]
        bounds = [cell.getchannel("A").getbbox() for cell in cells]
        if any(bound is None for bound in bounds):
            raise ValueError(f"animation row {row} contains an empty frame")
        visible_bounds = [bound for bound in bounds if bound is not None]

        anchors: list[tuple[float, int]] = []
        for cell, bound in zip(cells, visible_bounds):
            alpha = cell.getchannel("A")
            lower_top = bound[1] + round((bound[3] - bound[1]) * 0.65)
            lower = alpha.crop((bound[0], lower_top, bound[2], bound[3]))
            weights = list(lower.getdata())
            total = sum(weights)
            if not total:
                raise ValueError(f"animation row {row} has no lower-body anchor")
            anchor_x = bound[0] + sum(
                (index % lower.width) * weight
                for index, weight in enumerate(weights)
            ) / total
            anchors.append((anchor_x, bound[3]))

        left_extent = max(
            anchor_x - bound[0]
            for bound, (anchor_x, _) in zip(visible_bounds, anchors)
        )
        right_extent = max(
            bound[2] - anchor_x
            for bound, (anchor_x, _) in zip(visible_bounds, anchors)
        )
        row_height = max(bound[3] - bound[1] for bound in visible_bounds)
        anchor_target_x = round(left_extent)
        row_width = anchor_target_x + round(right_extent)

        aligned: list[Image.Image] = []
        for cell, bound, (anchor_x, _) in zip(cells, visible_bounds, anchors):
            subject = cell.crop(bound)
            frame = Image.new("RGBA", (row_width, row_height), (0, 0, 0, 0))
            x = round(anchor_target_x - (anchor_x - bound[0]))
            y = row_height - subject.height
            frame.alpha_composite(subject, (x, y))
            aligned.append(remove_transparent_rgb(frame))
        rows.append(aligned)
    return rows[0], rows[1]


def feathered_region_mask(
    size: tuple[int, int],
    box: tuple[int, int, int, int],
    *,
    blur_radius: int,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(box, radius=blur_radius * 3, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur_radius))


def isolate_idle_eye_motion(frames: list[Image.Image]) -> list[Image.Image]:
    """Official 6-frame idle: GitHub open and fully-closed lids only, body locked."""
    open_frame = render_pose(frames[0])
    # Source order is open, half, closed, open. Skip the half-blink entirely.
    closed_source = render_pose(frames[2])
    aligned_closed = Image.new("RGBA", open_frame.size, (0, 0, 0, 0))
    aligned_closed.alpha_composite(closed_source, (1, -1))
    eye_mask = feathered_region_mask(open_frame.size, IDLE_EYE_BOX, blur_radius=2)
    closed = remove_transparent_rgb(Image.composite(aligned_closed, open_frame, eye_mask))
    return [
        open_frame.copy(),
        closed.copy(),
        closed.copy(),
        open_frame.copy(),
        open_frame.copy(),
        open_frame.copy(),
    ]


def isolate_wave_arm_motion(frames: list[Image.Image]) -> list[Image.Image]:
    """Keep the standing pose fixed and copy only the waving arm region."""
    base = frames[0]
    width, height = base.size
    arm_mask = feathered_region_mask(
        base.size,
        (
            0,
            round(height * 0.14),
            round(width * 0.57),
            round(height * 0.66),
        ),
        blur_radius=4,
    )
    # The feathered arm mask previously leaked a few pixels into the left edge
    # of the face. Multiply by a feathered inverse face guard so every facial
    # pixel remains identical while the raised hand and sleeve animate.
    face_guard = Image.new("L", base.size, 255)
    guard_draw = ImageDraw.Draw(face_guard)
    guard_draw.rounded_rectangle(
        (
            round(width * 0.24),
            round(height * 0.10),
            round(width * 0.86),
            round(height * 0.61),
        ),
        radius=round(width * 0.12),
        fill=0,
    )
    face_guard = face_guard.filter(ImageFilter.GaussianBlur(2))
    arm_mask = ImageChops.multiply(arm_mask, face_guard)
    return [
        remove_transparent_rgb(Image.composite(frame, base, arm_mask))
        for frame in frames
    ]


def lock_frame_region(
    frames: list[Image.Image],
    box: tuple[int, int, int, int],
) -> list[Image.Image]:
    """Copy one anchor patch into every frame for exact pixel stability."""
    anchor = frames[0].crop(box)
    locked = [frames[0]]
    for frame in frames[1:]:
        result = frame.copy()
        result.paste(anchor, box[:2])
        locked.append(remove_transparent_rgb(result))
    return locked


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


def make_rows(
    poses: list[Image.Image],
    wave_sources: list[Image.Image],
    idle_sources: list[Image.Image],
) -> list[list[Image.Image]]:
    transparent = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    rows: list[list[Image.Image]] = []

    idle = isolate_idle_eye_motion(idle_sources)
    rows.append(idle + [transparent.copy() for _ in range(2)])

    run_motion = ((-2, 0), (-1, -2), (0, -3), (1, -1), (2, 0), (1, -2), (0, -3), (-1, -1))
    rows.append([render_pose(poses[1], dx=dx, dy=dy, max_width=184) for dx, dy in run_motion])
    rows.append([render_pose(poses[1], dx=-dx, dy=dy, flip=True, max_width=184) for dx, dy in run_motion])

    wave_keyframes = isolate_wave_arm_motion(wave_sources)
    wave_order = (0, 1, 2, 3, 2, 1, 0, 1)
    wave = [render_pose(wave_keyframes[index]) for index in wave_order]
    wave = lock_frame_region(wave, WAVE_FACE_LOCK_BOX)
    rows.append(wave)
    # Codex v2 reserves row 4 for the pointer-hover "jump" state. Reuse the
    # grounded wave cycle here so hovering never makes Hildegard jump.
    rows.append([frame.copy() for frame in wave])

    rows.append([render_pose(poses[5]) for _ in range(8)])

    waiting = [render_pose(poses[6]) for _ in range(6)]
    rows.append(waiting + [transparent.copy() for _ in range(2)])

    working = [render_pose(poses[7], max_width=188, max_height=194) for _ in range(6)]
    rows.append(working + [transparent.copy() for _ in range(2)])

    review = [render_pose(poses[8]) for _ in range(6)]
    rows.append(review + [transparent.copy() for _ in range(2)])

    look_frame = render_pose(idle_sources[0])
    rows.append([look_frame.copy() for _ in range(8)])
    rows.append([look_frame.copy() for _ in range(8)])

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
    gif_frames[0].save(
        IDLE_GIF_PATH,
        save_all=True,
        append_images=gif_frames[1:],
        duration=list(IDLE_DURATIONS_MS),
        loop=0,
        disposal=2,
        transparency=0,
    )


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    animation_source = Image.open(ANIMATION_SOURCE).convert("RGBA")
    poses = extract_poses(source)
    wave_sources, idle_sources = extract_animation_rows(animation_source)
    rows = make_rows(poses, wave_sources, idle_sources)
    atlas = build_atlas(rows)

    ROOT.joinpath("package").mkdir(exist_ok=True)
    ROOT.joinpath("assets").mkdir(exist_ok=True)
    ROOT.joinpath("qa").mkdir(exist_ok=True)

    atlas.save(ATLAS_PATH, "WEBP", lossless=True, method=6, exact=True)
    build_contact_sheet(rows).save(CONTACT_SHEET_PATH, "PNG", optimize=True)
    build_look_sheet(rows).save(LOOK_SHEET_PATH, "PNG", optimize=True)
    save_idle_gif(rows[0][:6])

    report = {"source": str(SOURCE.relative_to(ROOT)), "sourceSize": list(source.size), "animationSource": str(ANIMATION_SOURCE.relative_to(ROOT)), "animationSourceSize": list(animation_source.size), "poseCount": len(poses), "atlas": str(ATLAS_PATH.relative_to(ROOT)), "atlasSize": list(atlas.size), "grid": [COLUMNS, ROWS], "cellSize": [CELL_WIDTH, CELL_HEIGHT], "activeFrames": list(ACTIVE_FRAMES)}
    BUILD_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {ATLAS_PATH.relative_to(ROOT)}: {atlas.size[0]}×{atlas.size[1]}")
    print("Generated contact sheet, look-direction sheet, idle GIF and build report")


if __name__ == "__main__":
    main()
