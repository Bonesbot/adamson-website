@echo off
cd /d C:\Users\Bones\automation\AG_website
echo.
echo Pushing off-market commit to GitHub...
echo.
echo   src/pages/off-market.astro
echo   netlify/functions/off-market-lead.js
echo   src/components/layout/Footer.astro
echo   supabase/migrations/off_market_leads.sql
echo.
git push origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo SUCCESS: All files pushed. Netlify will auto-deploy in ~60 seconds.
    echo.
    echo NEXT STEP: Run the Supabase migration before the first form submission:
    echo   Dashboard ^> SQL Editor ^> open supabase/migrations/off_market_leads.sql ^> Run
) else (
    echo ERROR: push failed. Check git credentials and try again.
)
echo.
pause
