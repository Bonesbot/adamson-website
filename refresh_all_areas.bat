@echo off
REM Area-stats refresh -> single bundled commit -> ONE Netlify build (only if data changed).
REM Run AFTER the daily MLS ingest, on a 3-day cadence (see schtasks command in setup notes).
cd /d C:\Users\Bones\automation\AG_website
echo Refreshing area stats from Supabase (publishes at most one bundled build)...
python scripts\refresh_all_areas.py
echo.
echo Done. You can close this window.
