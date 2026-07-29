#!/usr/bin/env python3
"""Turn the profile photo into a self-typing ASCII SVG.

The only required dependency is Pillow. If ``rembg`` is installed, the script
uses it for a cleaner cut-out; otherwise it applies a deterministic crop,
background-colour suppression and a feathered portrait mask. The fallback is
useful for rebuilding the checked-in SVG without downloading a large model.
"""

import argparse
import base64
import html
import math
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


RAMP = " .`:-=+*cs#%@"
FONT_SIZE = 12.9
CHAR_W = 7.74  # JetBrains Mono is exactly 0.600 em wide.
LINE_H = 15
PAD = 14


def crop_portrait(image):
    """Use the face-and-torso area of the current square GitHub avatar."""
    width, height = image.size
    box = (
        round(width * 0.27),
        round(height * 0.27),
        round(width * 0.73),
        round(height * 0.80),
    )
    return image.crop(box)


def optional_cutout(image):
    """Prefer rembg when available; keep a lightweight offline fallback."""
    try:
        from rembg import remove
    except ImportError:
        return None
    return remove(image.convert("RGBA"))


def fallback_cutout(image):
    """Suppress the mint background and softly fade the outer frame."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()

    for y in range(height):
        for x in range(width):
            red, green, blue, _ = pixels[x, y]

            # The current avatar's siding is mint/green. This removes it while
            # leaving skin, hair, clothes and the dark camera strap intact.
            chroma_green = green - max(red, blue)
            chroma_blue = blue - max(red, green)
            background = (
                (chroma_green > 2 and green > 60)
                or (chroma_blue > 8 and blue > 70)
            )

            nx = (x - width * 0.50) / (width * 0.47)
            ny = (y - height * 0.48) / (height * 0.55)
            radius = nx * nx + ny * ny
            feather = max(0.0, min(1.0, (0.95 - radius) / 0.18))

            keep = feather * (0.0 if background else 1.0)
            alpha = round(255 * keep)
            pixels[x, y] = (red, green, blue, alpha)
    return rgba


def composite_white(image):
    white = Image.new("RGBA", image.size, "white")
    return Image.alpha_composite(white, image.convert("RGBA")).convert("RGB")


def prepare(image, columns):
    image = crop_portrait(image)
    cutout = optional_cutout(image) or fallback_cutout(image)
    image = composite_white(cutout)

    rows = max(1, round(columns * image.height / image.width * 0.48))
    image = image.resize((columns, rows), Image.Resampling.LANCZOS)
    image = image.convert("L").filter(ImageFilter.MedianFilter(3))
    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Contrast(image).enhance(1.18)

    # Darken mid-tones so small facial features survive the character mapping.
    image = image.point(
        lambda value: round(20 + 235 * ((value / 255) ** 1.20))
    )
    return image


def ascii_rows(image):
    rows = []
    for y in range(image.height):
        line = "".join(
            RAMP[min(len(RAMP) - 1, value * len(RAMP) // 256)]
            for value in (255 - image.getpixel((x, y)) for x in range(image.width))
        ).rstrip()
        rows.append(line)

    # Drop completely blank rows while preserving the portrait's inner spacing.
    while rows and not rows[0]:
        rows.pop(0)
    while rows and not rows[-1]:
        rows.pop()
    return rows


def font_rule(font_path):
    encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
    return (
        "@font-face{font-family:JBMono;font-style:normal;font-weight:400;"
        "font-display:block;src:url(data:font/woff2;base64,"
        + encoded
        + ") format('woff2')}"
    )


def render_svg(rows, font_path, animated=True):
    width = math.ceil(max((len(row) for row in rows), default=1) * CHAR_W + PAD * 2)
    height = len(rows) * LINE_H + PAD * 2
    family = (
        "JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace"
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{family}">',
        f"<style>{font_rule(font_path)}.a{{fill:#57606a}}"
        "@media(prefers-color-scheme:dark){.a{fill:#c9d1d9}}</style>",
    ]

    for index, row in enumerate(rows):
        y = PAD + index * LINE_H
        reveal_width = max(1, len(row)) * CHAR_W
        begin = index * 0.09
        clip_id = f"c{index}"
        safe = html.escape(row, quote=False)
        if not animated:
            parts.append(
                f'<text xml:space="preserve" x="{PAD}" y="{y + 11.2:.1f}" '
                f'class="a" font-size="{FONT_SIZE}">{safe}</text>'
            )
            continue
        parts.append(
            f'<clipPath id="{clip_id}"><rect x="{PAD}" y="{y}" height="{LINE_H}" width="0">'
            f'<animate attributeName="width" from="0" to="{reveal_width:.1f}" '
            f'begin="{begin:.2f}s" dur="0.09s" fill="freeze"/></rect></clipPath>'
            f'<g clip-path="url(#{clip_id})"><text xml:space="preserve" x="{PAD}" '
            f'y="{y + 11.2:.1f}" class="a" font-size="{FONT_SIZE}">{safe}</text></g>'
            f'<rect y="{y + 1}" width="6" height="12" class="a" opacity="0">'
            f'<animate attributeName="x" from="{PAD}" to="{PAD + reveal_width:.1f}" '
            f'begin="{begin:.2f}s" dur="0.09s" fill="freeze"/>'
            f'<set attributeName="opacity" to="0.8" begin="{begin:.2f}s"/>'
            f'<set attributeName="opacity" to="0" begin="{begin + 0.09:.2f}s"/></rect>'
        )
    parts.append("</svg>")
    return "".join(parts)


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default=root / "assets/avatar.jpg", type=Path)
    parser.add_argument("--output", default=root / "ascii.svg", type=Path)
    parser.add_argument("--columns", default=90, type=int)
    parser.add_argument("--static", action="store_true", help="omit SMIL for a still preview")
    parser.add_argument("--debug-raster", type=Path, help="save the processed grayscale grid")
    args = parser.parse_args()

    image = Image.open(args.source)
    prepared = prepare(image, args.columns)
    if args.debug_raster:
        prepared.resize(
            (prepared.width * 8, prepared.height * 15), Image.Resampling.NEAREST
        ).save(args.debug_raster)
    rows = ascii_rows(prepared)
    svg = render_svg(
        rows,
        root / "scripts/fonts/jbmono-ramp.woff2",
        animated=not args.static,
    )
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output}: {len(rows)} rows, {args.columns} columns")


if __name__ == "__main__":
    main()
