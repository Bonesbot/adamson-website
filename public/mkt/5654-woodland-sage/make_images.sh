#!/usr/bin/env bash
# Builds the web images for the 5654 Woodland Sage page from the originals in ./src (ImageMagick).
# Originals are kept out of git; copy them into ./src to re-run.
#   src/front.jpg    -> hero-desktop (full frame, house on the right) and hero-mobile (portrait crop on the house)
#   src/aerial.jpg   -> photo-1 (the lot, the cul-de-sac and the lake)
#   src/backyard.jpg -> photo-2 (4:3 crop, fenced yard)
set -euo pipefail
cd "$(dirname "$0")"
web(){ convert "$1" -quality 80 -define webp:method=6 "${1%.jpg}.webp"; }
convert src/front.jpg -auto-orient -strip -resize 2400x2400\> -quality 82 hero-desktop.jpg; web hero-desktop.jpg
convert src/front.jpg -auto-orient -strip -crop 900x1192+1560+0 +repage -quality 84 hero-mobile.jpg; web hero-mobile.jpg
convert src/aerial.jpg -auto-orient -strip -crop 1600x1200+430+0 +repage -resize 1400x -quality 82 photo-1.jpg; web photo-1.jpg
convert src/backyard.jpg -auto-orient -strip -gravity center -crop 1600x1200+0+0 +repage -resize 1400x -quality 82 photo-2.jpg; web photo-2.jpg
ls -la *.jpg *.webp
