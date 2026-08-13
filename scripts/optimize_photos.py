#!/usr/bin/env python3
"""
Web-optimize a folder of camera photos for the site.

  python3 optimize_photos.py <src-dir> <out-dir> [--width 1600] [--quality 82]

For each image: converts HEIC/HEIF (browsers can't render it), strips ALL metadata
(phone photos carry GPS — these go on a public page), resizes to a sane max width,
and writes both JPEG and WebP. Prints a before/after table.

Deliberately NOT clever about cropping: the page's CSS decides framing.
"""
import argparse, sys
from pathlib import Path

from PIL import Image, ImageOps
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except ImportError:                                   # jpeg-only run still works
    HEIF = False

EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}


def slugify(name):
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=82)
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXT)
    if not files:
        sys.exit(f"no images in {src}")
    print(f"{'source':<44} {'in':>8}  {'out(jpg)':>9} {'out(webp)':>10}  dimensions")
    total_in = total_out = 0
    for p in files:
        if p.suffix.lower() in (".heic", ".heif") and not HEIF:
            print(f"{p.name:<44} SKIPPED — pip install pillow-heif")
            continue
        try:
            im = Image.open(p)
        except Exception as e:
            print(f"{p.name:<44} FAILED — {e}")
            continue
        im = ImageOps.exif_transpose(im)               # honour rotation, then drop EXIF
        im = im.convert("RGB")
        if im.width > a.width:
            im = im.resize((a.width, round(im.height * a.width / im.width)), Image.LANCZOS)
        clean = Image.new("RGB", im.size)              # new canvas = no metadata carried over
        clean.paste(im)

        stem = slugify(p.stem)
        j, w = out / f"{stem}.jpg", out / f"{stem}.webp"
        clean.save(j, "JPEG", quality=a.quality, optimize=True, progressive=True)
        clean.save(w, "WEBP", quality=a.quality, method=6)
        total_in += p.stat().st_size
        total_out += j.stat().st_size
        print(f"{p.name:<44} {p.stat().st_size/1e6:7.1f}M  {j.stat().st_size/1e3:8.0f}K "
              f"{w.stat().st_size/1e3:9.0f}K  {clean.width}x{clean.height}  -> {stem}")
    print(f"\n{total_in/1e6:.1f}MB -> {total_out/1e6:.1f}MB jpeg "
          f"({100 - 100*total_out/max(total_in,1):.0f}% smaller), EXIF stripped")


if __name__ == "__main__":
    main()
