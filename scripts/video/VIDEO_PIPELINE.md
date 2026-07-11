# Adamson Group — Social Video Pipeline

Raw drone / iPhone footage → branded, post-ready social clips. Proven end-to-end 2026-07-10
(test export: `adamson-sandbar-reel-9x16.mp4` from `video-in/DJI_0025.MP4`).

## Flow

```
Drive video-in/ (or OneDrive)          ← stage raw mp4 here
        │  1. INTAKE      download to sandbox (resumable curl vs. drive.usercontent)
        ▼
   ffprobe + contact sheet             ← deterministic, 0 tokens
        │  2. SHOT SELECT  one vision pass over the contact sheet → EDL JSON
        ▼
   creative brief                      ← hook line, avatar script, CTA (brand guardrails)
        │  3. AVATAR       HeyGen v3, transparent webm (sandbox CAN reach api.heygen.com)
        ▼
   4. RENDER  ffmpeg from template + EDL — crop/pan 9:16, grade, hook text,
              watermark, avatar bubble, end card, voice track   ← deterministic, 0 tokens
        ▼
   5. QC      frame sampling + volumedetect + duration check (one cheap vision pass)
        ▼
   6. DISTRIBUTE  Drive video-out/ drafts today → YouTube/Meta APIs later
```

## Model routing (token efficiency)

| Step | Engine | Why |
|---|---|---|
| Download, probe, thumbnails, render, export, upload | ffmpeg / python — **0 tokens** | Deterministic; never ask an LLM to do pixel work |
| Status polling, file naming, caption fill-in from template | Haiku-class | Mechanical text |
| Shot selection (contact sheet vision), hook + avatar script copy | Sonnet-class | One image + ~200 output tokens per video |
| New template design, campaign concepts, pipeline changes | Fable/Opus | Rare, high-leverage only |

The expensive creative pass happens **once per video** (a single contact-sheet image + a short
EDL/script). Everything downstream is scripted, so re-renders and platform variants cost zero
tokens and always look identical.

## Branding uniformity

All visual decisions live in `templates/coastal-luxury.json` — navy `#0A1F3C`, gold `#C9A961`,
Playfair Display headlines, white AG logo watermark (top-right, 55% opacity), gold-ring circular
avatar bubble (bottom-left, IG video-note style), navy end card with AdamsonFL.com CTA, and the
color grade (`contrast 1.07 / sat 1.20 / soft vignette`). Change the template once → every
future video inherits it. New "vibes" = new template file, not new code.

## Avatar registry

| Person | Group | Look (avatar_id) | Voice |
|---|---|---|---|
| Ryan (latest) | Ryan3 `e4ccd9ff…` | Slim Navy Sport Coat `ccabb086270f4e94ade5058683e53710` | Ryan V1 `ce2fae3761df4cdb973a65adfc54ede5` |
| Ryan (legacy) | Ryan2 (PHOTO) `618eb685…` | — | same |
| Kelli | TBD — needs a HeyGen avatar group created | — | TBD |

HeyGen call: `POST /v3/videos` `{type:avatar, output_format:webm, remove_background:true}` —
same pattern as `market_minute.py`. **Note (supersedes old memory): the Cowork sandbox reached
api.heygen.com fine on 2026-07-10** — local runs are a fallback, not a requirement.

## Platform presets

| Preset | Size | Notes |
|---|---|---|
| `ig-reel` / `yt-short` / `fb-reel` | 1080×1920 | ≤ 90 s; keep title-safe: no UI-critical content right edge / bottom 320 px |
| `ig-feed` | 1080×1350 | 4:5 crop of same render |
| `yt` | 1920×1080 | 16:9, no vertical crop, watermark + end card only |

Voice-only exports by default (add trending audio in the IG app at post time — user decision
2026-07-10). `--music file.m4a` ducks a bed −18 dB under the voice when wanted.

## Distribution (today → next)

- **Today:** finished drafts land in Drive `video-out/` next to `video-in/`; post manually.
- **Next:** YouTube Data API `videos.insert` (privacyStatus=private → review → publish);
  Meta Graph API Reels publish for IG/FB (needs IG Business account + long-lived token);
  schedule as a Cowork task (`social-video` job, same pattern as `mls-export`).

## Repo layout

```
scripts/video/
  market_minute.py            # existing weekly LBK data video
  social_reel.py              # this pipeline (footage → reel)
  templates/coastal-luxury.json
  VIDEO_PIPELINE.md           # this doc
```

Run: `python scripts/video/social_reel.py --footage <drive-file-id> --edl edl.json \
      --avatar ryan --preset ig-reel [--music track.m4a] [--hook "line1|line2"] --script "…"`
