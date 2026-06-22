# Market Minute video pipeline

Generates the branded "avatar over a clean LBK photo + live data panel" video.

```
data (Supabase)  ->  avatar (HeyGen v3, transparent webm)  ->  ffmpeg composite  ->  MP4
```

## Swap in your better avatar
Open `market_minute.py` and change one line:

```python
AVATAR_ID = "618eb685f6124a7ca0fdc32c248444fc"   # <-- your new Digital Twin look id
```

Find new look ids in HeyGen with your key:
`GET https://api.heygen.com/v3/avatars/looks?avatar_type=digital_twin&ownership=private`
(or just tell Claude "new avatar's ready" and it'll grab the newest id for you.)

Other knobs at the top of the script: `VOICE_ID`, `WINDOW_DAYS`, `BG_IMAGE`,
`AVATAR_H` (overlay height — lower = smaller head, ~360 ≈ 20-25% of frame),
`RESOLUTION`, and the brand colors.

## Run it (on your machine — not the Cowork sandbox)
HeyGen's REST API responds reliably from your machine; the sandbox can't render it.

```
cd C:\Users\Bones\automation\AG_website
pip install psycopg2-binary pillow          # one-time
python scripts/video/market_minute.py
# -> scripts/video/out/market-minute.mp4
```

Reads `HEYGEN_API_KEY` + `DATABASE_URL` from the repo-root `.env` (already present).

## What's tunable later
- Avatar size/position (`AVATAR_H`, the overlay x/y in `composite()`)
- Data panel design (`build_panel()` — fonts, layout, animated count-ups)
- Background photo (`BG_IMAGE` — any LBK aerial/beachfront; can rotate weekly)
- Intro/outro motion, lower-third name bar, logo

## Wiring to weekly automation (next step)
Schedule this to run weekly, then drop the output onto the site by replacing
`public/videos/lbk-market-minute.mp4` and committing — the area page already
embeds that path with VideoObject schema, so it updates on the next build.

## Status of the avatar
The prototype used Digital Twin `618eb685...` (matting-enabled, transparent webm
confirmed) + cloned voice `Ryan V1`. Replace the avatar id once you've made a
more realistic Digital Twin in HeyGen.
