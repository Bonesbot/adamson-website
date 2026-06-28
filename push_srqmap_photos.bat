@echo off
cd /d C:\Users\Bones\automation\AG_website
echo Ingesting SRQmap pin photos from assets\SRQmap ...
python scripts\build_srqmap_photos.py
echo.
echo Done. You can close this window.
pause
