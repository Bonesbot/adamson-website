#!/usr/bin/env bash
# Builds the web images for the 4539 Bay Club landing page from the originals in ./src.
# Run from this folder on BonesBot (ImageMagick): bash make_images.sh
#   src/aerial-feb-2025.jpg  -> hero-desktop.{jpg,webp} (1920w) and hero-mobile.{jpg,webp} (1080w, portrait crop)
#   src/44-DJI_0784.jpg      -> cbc-1.{jpg,webp}
#   src/4449 (99)_MLS.jpg    -> cbc-2.{jpg,webp}
#   src/4557 (42)_MLS.jpg    -> cbc-3.{jpg,webp}
set -euo pipefail
cd "$(dirname "$0")"
pick(){ for f in "$@"; do [ -f "src/$f" ] && { echo "src/$f"; return; }; done; return 1; }
HERO=$(pick "aerial-feb-2025.jpg" "Aerial - Feb 2025 - towards Bay.jpg") || { echo "no aerial in src/"; exit 1; }
G1=$(pick "44-DJI_0784.jpg" "dji-0784.jpg") || true
G2=$(pick "4449 (99)_MLS.jpg" "4449-99-mls.jpg") || true
G3=$(pick "4557 (42)_MLS.jpg" "4557-42-mls.jpg") || true

convert "$HERO" -auto-orient -strip -resize 1920x1920\> -quality 82 hero-desktop.jpg
convert hero-desktop.jpg -quality 80 -define webp:method=6 hero-desktop.webp
# phone: 9:16 crop around the center of the aerial, 1080 wide
convert "$HERO" -auto-orient -strip -resize x1920 -gravity center -crop 1080x1920+0+0 +repage -quality 82 hero-mobile.jpg
convert hero-mobile.jpg -quality 80 -define webp:method=6 hero-mobile.webp

i=1
for f in "$G1" "$G2" "$G3"; do
  [ -n "$f" ] || { i=$((i+1)); continue; }
  convert "$f" -auto-orient -strip -resize 1400x1400\> -gravity center -extent "%[fx:w]x%[fx:round(w*3/4)]" -quality 82 "cbc-$i.jpg" 2>/dev/null || convert "$f" -auto-orient -strip -resize 1400x1400\> -quality 82 "cbc-$i.jpg"
  convert "cbc-$i.jpg" -quality 80 -define webp:method=6 "cbc-$i.webp"
  i=$((i+1))
done
ls -la *.jpg *.webp
