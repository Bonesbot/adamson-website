#!/usr/bin/env python3
"""
build_area_media.py - turn a folder of raw photos into web-ready area imagery.

One command takes whatever came off a phone or a drone and produces everything an
area page needs: a hero, a gallery, WebP alongside JPEG, a contact sheet to review
from, and a proposed area-media.json block.

    python scripts/build_area_media.py --slug siesta-key --src _incoming/siesta-key

What it does, in order:

  1. Reads every JPG/JPEG/PNG/HEIC/HEIF in --src (HEIC via pillow-heif).
  2. Honors the EXIF orientation tag, so phone shots are not sideways.
  3. Pulls EXIF GPS where present and labels each frame with the nearest known
     landmark, so a drone still named DJI_0796.JPG becomes "Point of Rocks".
  4. Resizes: hero at --hero-width (default 2400), gallery at --gallery-width
     (default 1600), longest edge, never upscaling.
  5. Encodes JPEG (quality 82, progressive) and WebP (quality 80) for each output.
     EXIF is stripped from what ships: it is dead weight on a web image and drone
     GPS does not belong in a public asset.
  6. Writes a contact sheet so the frames can be reviewed and captioned without
     opening sixteen files.
  7. Emits a proposed area-media.json gallery block, filenames and dimensions
     filled in, alt and caption left as TODO for a human.

It never writes to area-media.json itself. Captions and alt text are editorial and
get written by a person; this script only proposes the scaffold.

Idempotent: re-running overwrites its own outputs and touches nothing else.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ExifTags

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:  # pragma: no cover
    HEIC_OK = False

RASTER = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

# Nearest-landmark labelling. Same idea as the point-in-polygon area tagging in
# Media-Studio/ARCHIVE.md, scaled down to one island: a coordinate is worth more
# than a filename. Add entries per area as needed.
LANDMARKS = {
    "siesta-key": [
        ("Siesta Key Village", 27.2734, -82.5507),
        ("Siesta Beach", 27.2664, -82.5486),
        ("Crescent Beach", 27.2551, -82.5479),
        ("Point of Rocks", 27.2478, -82.5450),
        ("Turtle Beach", 27.2172, -82.5133),
        ("Midnight Pass", 27.2119, -82.5106),
        ("Big Pass", 27.2830, -82.5560),
        ("Bird Key / north bridge", 27.2861, -82.5453),
    ],
    "downtown-sarasota": [
        ("Five Points", 27.3364, -82.5407),
        ("Sarasota Opera House", 27.3335, -82.5375),
        ("Burns Court", 27.3307, -82.5366),
        ("Bayfront Park", 27.3325, -82.5493),
        ("Marina Jack", 27.3341, -82.5488),
        ("The Bay Park", 27.3410, -82.5490),
        ("Van Wezel", 27.3437, -82.5498),
        ("Rosemary District", 27.3430, -82.5400),
        ("Golden Gate Point", 27.3318, -82.5527),
        ("Ringling Causeway Bridge", 27.3295, -82.5620),
        ("Bird Key Park", 27.3246, -82.5686),
        ("Selby Gardens", 27.3222, -82.5423),
        ("Payne Park", 27.3339, -82.5290),
    ],
    "longboat-key": [
        ("Longboat Key Club", 27.3616, -82.6236),
        ("Beer Can Island", 27.4290, -82.6870),
        ("Bayfront Park", 27.3195, -82.5836),
    ],
}

GPS_MAX_KM = 3.0  # beyond this, do not claim a landmark


def eprint(*a):
    print(*a, file=sys.stderr)


def slugify(text: str) -> str:
    text = re.sub(r"\.[A-Za-z0-9]+$", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text) or "frame"


def _ratio(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return v.numerator / v.denominator
        except Exception:
            return 0.0


def exif_gps(img: Image.Image):
    """Return (lat, lon) in signed decimal degrees, or None."""
    try:
        raw = img.getexif()
        if not raw:
            return None
        gps_ifd = raw.get_ifd(ExifTags.IFD.GPSInfo)
        if not gps_ifd:
            return None
        tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        lat, lat_ref = tags.get("GPSLatitude"), tags.get("GPSLatitudeRef")
        lon, lon_ref = tags.get("GPSLongitude"), tags.get("GPSLongitudeRef")
        if not lat or not lon:
            return None

        def dms(v):
            d, m, s = (_ratio(x) for x in v)
            return d + m / 60.0 + s / 3600.0

        la, lo = dms(lat), dms(lon)
        if str(lat_ref).upper().startswith("S"):
            la = -la
        if str(lon_ref).upper().startswith("W"):
            lo = -lo
        if la == 0 and lo == 0:
            return None
        return (round(la, 6), round(lo, 6))
    except Exception:
        return None


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_landmark(slug: str, lat: float, lon: float):
    best, best_km = None, None
    for name, la, lo in LANDMARKS.get(slug, []):
        km = haversine_km(lat, lon, la, lo)
        if best_km is None or km < best_km:
            best, best_km = name, km
    if best is None or best_km > GPS_MAX_KM:
        return None, best_km
    return best, best_km


def load(path: Path) -> Image.Image:
    if path.suffix.lower() in {".heic", ".heif"} and not HEIC_OK:
        raise RuntimeError(
            f"{path.name} is HEIC but pillow-heif is not installed. "
            "pip install pillow-heif --break-system-packages"
        )
    img = Image.open(path)
    img.load()
    return img


def crop_to_aspect(img: Image.Image, aspect: str, focus: str) -> Image.Image:
    """Largest window of the given W:H aspect, centred on a focal point and clamped
    inside the frame. Used for the card, where the page wants portrait and the source
    is almost always landscape, so a plain centre crop cuts the subject in half."""
    work = ImageOps.exif_transpose(img)
    aw, ah = (float(x) for x in aspect.split(":"))
    fx, fy = (float(x) / 100.0 for x in focus.split(","))
    w, h = work.size
    target = aw / ah

    if w / h > target:          # source is wider than the target: crop width
        cw, ch = int(round(h * target)), h
    else:                       # source is taller: crop height
        cw, ch = w, int(round(w / target))

    left = int(round(fx * w - cw / 2))
    top = int(round(fy * h - ch / 2))
    left = max(0, min(left, w - cw))
    top = max(0, min(top, h - ch))
    return work.crop((left, top, left + cw, top + ch))


def encode(img: Image.Image, out_base: Path, width: int, jpeg_q: int, webp_q: int):
    """Resize to `width` on the longest edge and write .jpg + .webp. Returns (w, h)."""
    work = ImageOps.exif_transpose(img)
    if work.mode not in ("RGB", "L"):
        work = work.convert("RGB")
    elif work.mode == "L":
        work = work.convert("RGB")

    w, h = work.size
    longest = max(w, h)
    if longest > width:
        scale = width / longest
        work = work.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

    out_base.parent.mkdir(parents=True, exist_ok=True)
    # No exif= argument: metadata is deliberately dropped on the way out.
    work.save(out_base.with_suffix(".jpg"), "JPEG", quality=jpeg_q,
              optimize=True, progressive=True)
    work.save(out_base.with_suffix(".webp"), "WEBP", quality=webp_q, method=6)
    return work.size


def contact_sheet(frames, out_path: Path, cols=4, tile=460, pad=12):
    """Grid of every frame, each stamped with its index and output name."""
    if not frames:
        return
    rows = math.ceil(len(frames) / cols)
    label_h = 34
    cell_w, cell_h = tile, tile + label_h
    sheet = Image.new(
        "RGB", (cols * cell_w + pad * (cols + 1), rows * cell_h + pad * (rows + 1)), "#12161c"
    )
    draw = ImageDraw.Draw(sheet)

    for i, fr in enumerate(frames):
        thumb = ImageOps.exif_transpose(Image.open(fr["preview_path"]))
        thumb = thumb.convert("RGB")
        thumb.thumbnail((tile, tile), Image.LANCZOS)
        x = pad + (i % cols) * (cell_w + pad)
        y = pad + (i // cols) * (cell_h + pad)
        sheet.paste(thumb, (x + (tile - thumb.width) // 2, y + (tile - thumb.height) // 2))
        tag = f"[{i + 1:02d}] {fr['name']}"
        if fr.get("landmark"):
            tag += f"  ~{fr['landmark']}"
        draw.text((x + 4, y + tile + 8), tag[:64], fill="#e8eaed")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="area slug, e.g. siesta-key")
    ap.add_argument("--src", required=True, help="folder of raw photos")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    ap.add_argument("--hero", default=None,
                    help="filename (or fragment) of the raw file to use as the hero")
    ap.add_argument("--hero-width", type=int, default=2400)
    ap.add_argument("--gallery-width", type=int, default=1600)
    ap.add_argument("--jpeg-quality", type=int, default=82)
    ap.add_argument("--webp-quality", type=int, default=80)
    ap.add_argument("--limit", type=int, default=0, help="cap gallery frames (0 = all)")
    ap.add_argument("--crop", action="append", default=[], metavar="FRAG=W:H@X,Y",
                    help="pre-crop a gallery frame before resizing, e.g. "
                         "--crop 'mid-bridge=4:3@60,50'. Repeatable. For panoramas, "
                         "whose native aspect a 4:3 tile would butcher.")
    ap.add_argument("--card", default=None,
                    help="filename (or fragment) to build the portrait card image from")
    ap.add_argument("--card-aspect", default="3:4",
                    help="card aspect as W:H (default 3:4, matching AreaCard)")
    ap.add_argument("--card-width", type=int, default=1200,
                    help="longest edge of the card image in px (a 3:4 card at 1200 is 900x1200)")
    ap.add_argument("--card-focus", default="50,50",
                    help="focal point as X,Y percentages of the source (default centre)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    src = Path(args.src)
    if not src.is_absolute():
        src = (repo / src).resolve()
    if not src.is_dir():
        eprint(f"error: --src is not a directory: {src}")
        return 2

    out_dir = repo / "public" / "images" / "areas" / args.slug
    build_dir = repo / "_build" / args.slug

    raw = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in RASTER)
    if not raw:
        eprint(f"error: no images found in {src}")
        eprint(f"       looked for: {', '.join(sorted(RASTER))}")
        return 2

    skipped = sorted(
        p.name for p in src.iterdir()
        if p.is_file() and p.suffix.lower() not in RASTER
    )
    if skipped:
        eprint(f"note: {len(skipped)} non-image file(s) ignored: {', '.join(skipped[:6])}"
               + (" ..." if len(skipped) > 6 else ""))

    crops = {}
    for spec in args.crop:
        try:
            frag, rest = spec.split("=", 1)
            aspect, focus = rest.split("@", 1)
            crops[frag.lower()] = (aspect, focus)
        except ValueError:
            eprint(f"error: bad --crop '{spec}', expected FRAG=W:H@X,Y")
            return 2

    hero_pick = None
    if args.hero:
        needle = args.hero.lower()
        for p in raw:
            if needle in p.name.lower():
                hero_pick = p
                break
        if hero_pick is None:
            eprint(f"warning: --hero '{args.hero}' matched nothing; using the first frame")
    if hero_pick is None:
        hero_pick = raw[0]

    frames, hero_meta = [], None
    print(f"\n{len(raw)} source image(s) in {src}\n")
    print(f"{'file':<34} {'size':>12}  {'gps':>22}  landmark")
    print("-" * 96)

    gallery_n = 0
    for path in raw:
        try:
            img = load(path)
        except Exception as e:
            eprint(f"  skip {path.name}: {e}")
            continue

        gps = exif_gps(img)
        landmark, km = (None, None)
        if gps:
            landmark, km = nearest_landmark(args.slug, *gps)

        is_hero = path == hero_pick
        stem = slugify(path.stem)
        if is_hero:
            out_base = out_dir / "hero"
            width = args.hero_width
        else:
            if args.limit and gallery_n >= args.limit:
                print(f"{path.name:<34} {'-':>12}  {'-':>22}  (over --limit, skipped)")
                continue
            gallery_n += 1
            out_base = out_dir / f"gal-{stem}"
            width = args.gallery_width

        crop_spec = next((v for k, v in crops.items() if k in path.name.lower()), None)
        src_img = crop_to_aspect(img, *crop_spec) if crop_spec else img
        w, h = encode(src_img, out_base, width, args.jpeg_quality, args.webp_quality)

        gps_s = f"{gps[0]:.5f},{gps[1]:.5f}" if gps else "none"
        lm_s = f"{landmark} ({km:.2f} km)" if landmark else ("out of range" if gps else "")
        if crop_spec:
            lm_s = (lm_s + f"  [cropped {crop_spec[0]}@{crop_spec[1]}]").strip()
        print(f"{path.name:<34} {f'{w}x{h}':>12}  {gps_s:>22}  {lm_s}")

        rec = {
            "name": out_base.name,
            "source": path.name,
            "src": f"/images/areas/{args.slug}/{out_base.name}.jpg",
            "webp": f"/images/areas/{args.slug}/{out_base.name}.webp",
            "width": w,
            "height": h,
            "orientation": "landscape" if w >= h else "portrait",
            "gps": list(gps) if gps else None,
            "landmark": landmark,
            "preview_path": str(out_base.with_suffix(".jpg")),
        }
        if is_hero:
            hero_meta = rec
        else:
            frames.append(rec)

    if not frames and not hero_meta:
        eprint("error: nothing was encoded")
        return 1

    card_meta = None
    if args.card:
        needle = args.card.lower()
        card_src = next((p for p in raw if needle in p.name.lower()), None)
        if card_src is None:
            eprint(f"warning: --card '{args.card}' matched nothing; no card image written")
        else:
            cropped = crop_to_aspect(load(card_src), args.card_aspect, args.card_focus)
            cw, ch = encode(cropped, out_dir / "card", args.card_width,
                            args.jpeg_quality, args.webp_quality)
            card_meta = {
                "src": f"/images/areas/{args.slug}/card.jpg",
                "webp": f"/images/areas/{args.slug}/card.webp",
                "width": cw, "height": ch, "source": card_src.name,
            }
            print(f"\ncard: {card_src.name} -> {cw}x{ch} "
                  f"({args.card_aspect}, focus {args.card_focus})")

    sheet_path = build_dir / f"{args.slug}-contact-sheet.png"
    contact_sheet(([hero_meta] if hero_meta else []) + frames, sheet_path)

    proposal = {
        args.slug: {
            "cardImage": (card_meta["src"] if card_meta else f"/images/areas/{args.slug}.jpg"),
            **({"cardWebp": card_meta["webp"]} if card_meta else {}),
            **({"heroImage": hero_meta["src"], "heroWebp": hero_meta["webp"]} if hero_meta else {}),
            "gallery": [
                {
                    "src": f["src"],
                    "webp": f["webp"],
                    "alt": f"TODO alt text - {f['landmark'] or f['source']}",
                    "caption": f"TODO caption - {f['landmark'] or ''}".strip(" -"),
                }
                for f in frames
            ],
            "summary": "TODO summary",
        }
    }
    proposal_path = build_dir / f"{args.slug}-media.proposed.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")

    total_kb = sum(
        p.stat().st_size for p in out_dir.glob("*") if p.is_file()
    ) / 1024

    print("-" * 96)
    print(f"\nwrote {len(frames)} gallery frame(s)"
          + (" + hero" if hero_meta else "")
          + f" to {out_dir}")
    print(f"  total: {total_kb:,.0f} KB across .jpg + .webp")
    print(f"  contact sheet: {sheet_path}")
    print(f"  proposed block: {proposal_path}")
    print("\nNext: review the contact sheet, write real alt + caption text,")
    print(f"      then merge the block into src/data/area-media.json under '{args.slug}'.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
