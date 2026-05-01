from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


@dataclass(frozen=True)
class BrandInputs:
    aimm_light: Path
    aimm_dark: Path
    apogee_light: Path
    apogee_dark: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_rgba(img: Image.Image) -> Image.Image:
    return img.convert("RGBA") if img.mode != "RGBA" else img


def _avg_corner_rgb(img: Image.Image, *, pad: int = 8) -> tuple[int, int, int]:
    im = img.convert("RGB")
    w, h = im.size
    boxes = [
        (0, 0, min(w, pad), min(h, pad)),
        (max(0, w - pad), 0, w, min(h, pad)),
        (0, max(0, h - pad), min(w, pad), h),
        (max(0, w - pad), max(0, h - pad), w, h),
    ]
    total = [0, 0, 0]
    count = 0
    for b in boxes:
        crop = im.crop(b)
        px = list(crop.getdata())
        for r, g, b2 in px:
            total[0] += int(r)
            total[1] += int(g)
            total[2] += int(b2)
            count += 1
    if count <= 0:
        return (255, 255, 255)
    return (total[0] // count, total[1] // count, total[2] // count)


def _mask_non_bg(img: Image.Image, bg_rgb: tuple[int, int, int], *, threshold: int = 22) -> Image.Image:
    """
    Returns L mask where non-background pixels are 255.
    """
    im = img.convert("RGB")
    bg = Image.new("RGB", im.size, bg_rgb)
    diff = ImageChops.difference(im, bg).convert("L")
    # Threshold
    return diff.point(lambda p: 255 if p > threshold else 0, mode="L")


def _split_logo_and_text(mask: Image.Image) -> int | None:
    """
    Finds a horizontal split line (y) between logo mark and text using the mask's row density.
    Returns y index in [0..h], where crop(0,0,w,y) gives the top mark region.
    """
    w, h = mask.size
    rows = []
    data = mask.getdata()
    for y in range(h):
        row_sum = 0
        offset = y * w
        # count non-zero pixels
        for x in range(w):
            if data[offset + x]:
                row_sum += 1
        rows.append(row_sum)
    if not rows:
        return None
    max_row = max(rows)
    if max_row <= 0:
        return None
    # Find "content" rows above a density threshold.
    dense = [i for i, v in enumerate(rows) if v >= max(10, int(max_row * 0.08))]
    if not dense:
        return None
    top_end = dense[-1]
    # Search for a low-density valley after logo mark ends but before the bottom.
    start = int(h * 0.30)
    end = int(h * 0.88)
    best_y = None
    best_score = None
    for y in range(start, end):
        window = rows[y : min(h, y + 10)]
        if not window:
            continue
        score = sum(window) / len(window)
        if best_score is None or score < best_score:
            best_score = score
            best_y = y
    # Require a meaningful valley (gap) vs peak
    if best_y is None or (best_score is not None and best_score > max_row * 0.02):
        return None
    # Keep split above any dense text region if we detected it.
    return best_y


def _bbox_from_mask(mask: Image.Image) -> tuple[int, int, int, int] | None:
    bbox = mask.getbbox()
    if not bbox:
        return None
    l, t, r, b = bbox
    if (r - l) <= 1 or (b - t) <= 1:
        return None
    return (l, t, r, b)


def _extract_mark(img: Image.Image) -> Image.Image:
    base = img.copy()
    bg = _avg_corner_rgb(base)
    mask = _mask_non_bg(base, bg)
    split = _split_logo_and_text(mask)
    if split:
        base = base.crop((0, 0, base.size[0], split))
        mask = mask.crop((0, 0, mask.size[0], split))
    bbox = _bbox_from_mask(mask) or (0, 0, base.size[0], base.size[1])
    crop = base.crop(bbox)
    bg2 = _avg_corner_rgb(crop)
    # Build alpha from distance to bg
    rgb = crop.convert("RGB")
    bg_im = Image.new("RGB", rgb.size, bg2)
    diff = ImageChops.difference(rgb, bg_im).convert("L")
    # Smooth-ish alpha curve.
    alpha = diff.point(lambda p: 0 if p < 10 else int(min(255, (p - 10) * 3)), mode="L")
    out = _ensure_rgba(crop)
    out.putalpha(alpha)
    return out


def _pad_to_square(img: Image.Image, *, bg=(0, 0, 0, 0)) -> Image.Image:
    im = _ensure_rgba(img)
    w, h = im.size
    size = max(w, h)
    canvas = Image.new("RGBA", (size, size), bg)
    canvas.paste(im, ((size - w) // 2, (size - h) // 2), im)
    return canvas


def _resize(img: Image.Image, size: int) -> Image.Image:
    im = _ensure_rgba(img)
    return im.resize((size, size), Image.Resampling.LANCZOS)


def _rounded_rect_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def _gradient_bg(size: int) -> Image.Image:
    # Simple radial-ish gradient to keep icon readable (no external deps).
    base = Image.new("RGBA", (size, size), (9, 16, 40, 255))
    cx = cy = (size - 1) / 2.0
    pixels = base.load()
    for y in range(size):
        for x in range(size):
            dx = (x - cx) / (size * 0.55)
            dy = (y - cy) / (size * 0.55)
            r = math.sqrt(dx * dx + dy * dy)
            t = max(0.0, min(1.0, 1.0 - r))
            # Blend towards a slightly brighter blue in the center.
            br = int(9 + (40 - 9) * t)
            bg = int(16 + (70 - 16) * t)
            bb = int(40 + (120 - 40) * t)
            pixels[x, y] = (br, bg, bb, 255)
    return base


def _save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)


def main() -> int:
    root = _repo_root()
    inputs = BrandInputs(
        aimm_light=root / "docs" / "pics" / "aimm_light_cr.jpg",
        aimm_dark=root / "docs" / "pics" / "aimm_dark_cr.jpg",
        apogee_light=root / "docs" / "pics" / "apogee_light_cr.jpg",
        apogee_dark=root / "docs" / "pics" / "apogee_dark_cr.jpg",
    )
    for p in (inputs.aimm_light, inputs.aimm_dark, inputs.apogee_light, inputs.apogee_dark):
        if not p.exists():
            raise FileNotFoundError(str(p))

    assets = root / "src" / "aimn" / "ui" / "assets"

    aimm_light = Image.open(inputs.aimm_light)
    aimm_dark = Image.open(inputs.aimm_dark)
    apogee_light = Image.open(inputs.apogee_light)
    apogee_dark = Image.open(inputs.apogee_dark)

    mark = _extract_mark(aimm_light)
    mark = _pad_to_square(mark)
    mark_400 = _resize(mark, 400)
    _save_png(mark_400, assets / "logo_mark_light.png")

    mono = mark_400.convert("L")
    mono_rgba = Image.new("RGBA", mono.size, (0, 0, 0, 0))
    # Keep alpha from luminance so thin details remain visible.
    alpha = mono.point(lambda p: int(min(255, max(0, (255 - p) * 1.2))), mode="L")
    mono_rgba.putalpha(alpha)
    _save_png(mono_rgba, assets / "logo_mark_mono.png")

    # Wordmark / tile: keep as square tiles (400x400).
    tile_dark = _resize(_ensure_rgba(aimm_dark), 400)
    _save_png(tile_dark, assets / "logo_tile_dark.png")

    wordmark = _resize(_ensure_rgba(aimm_light), 400)
    _save_png(wordmark, assets / "logo_wordmark.png")

    # App icon: rounded square + mark.
    icon_bg = _gradient_bg(256)
    mask = _rounded_rect_mask(256, radius=54)
    icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    icon.paste(icon_bg, (0, 0))
    icon.putalpha(mask)
    mark_icon = _resize(mark, 188)
    icon.paste(mark_icon, ((256 - 188) // 2, (256 - 188) // 2), mark_icon)
    _save_png(icon, assets / "app_icon.png")

    # Company logos (not wired in UI yet, but bundled for future use).
    _save_png(_resize(_ensure_rgba(apogee_light), 400), assets / "apogee_wordmark_light.png")
    _save_png(_resize(_ensure_rgba(apogee_dark), 400), assets / "apogee_wordmark_dark.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

