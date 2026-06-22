#!/usr/bin/env python3
"""
Longboat Key "Market Minute" video pipeline  —  avatar-over-photo blend.

Produces a branded MP4: live MLS data panel (left) + matted HeyGen avatar
(bottom-right) composited over a clean LBK background photo.

  data (Supabase)  ->  avatar (HeyGen v3, transparent webm)  ->  ffmpeg composite

Swap in a better avatar by changing AVATAR_ID below. Everything else is reusable.

Requires (local machine, NOT the Cowork sandbox — HeyGen REST responds reliably
from your machine):  python3, ffmpeg, pip install psycopg2-binary pillow
Reads HEYGEN_API_KEY + DATABASE_URL from ../../.env (repo root).

Run:   python scripts/video/market_minute.py
Output: scripts/video/out/market-minute.mp4
"""
import os, re, sys, json, time, subprocess, urllib.request, urllib.error
from pathlib import Path

# ----------------------------- CONFIG (tune here) ----------------------------
AVATAR_ID   = "618eb685f6124a7ca0fdc32c248444fc"   # <-- SWAP with your new, more realistic Digital Twin look id
VOICE_ID    = "ce2fae3761df4cdb973a65adfc54ede5"   # Ryan V1 cloned voice
AREA_SLUG   = "longboat-key"
AREA_NAME   = "Longboat Key"
WINDOW_DAYS = 7
BG_IMAGE    = "public/images/areas/longboat-key/gal-beachfront.jpg"  # repo-relative
RESOLUTION  = "720p"           # 720p / 1080p / 4k
AVATAR_H    = 360              # avatar overlay height in px (lower = smaller head; ~360≈20-25%)
OUT_DIR     = "scripts/video/out"
# Brand
NAVY=(10,31,60,235); GOLD=(201,169,97,255); WHITE=(255,255,255,255); MUTED=(255,255,255,150)
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]          # repo root (scripts/video/ -> ../../)
def load_env():
    p = ROOT/".env"
    if p.exists():
        for ln in p.read_text().splitlines():
            ln=ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k,v=ln.split("=",1); os.environ.setdefault(k.strip(), v.strip())
load_env()
KEY = os.environ.get("HEYGEN_API_KEY",""); DB = os.environ.get("DATABASE_URL","")
assert KEY and DB, "HEYGEN_API_KEY and DATABASE_URL must be set (in .env)"
WORK = ROOT/OUT_DIR; WORK.mkdir(parents=True, exist_ok=True)

# ---- 1. data ----
def fetch_stats():
    import psycopg2
    c=psycopg2.connect(DB, connect_timeout=20); cur=c.cursor()
    cur.execute(f"""
      SELECT COUNT(*) FILTER (WHERE mls_status='Sold' AND close_date >= CURRENT_DATE - INTERVAL '{WINDOW_DAYS} days'),
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
               FILTER (WHERE mls_status='Sold' AND current_price IS NOT NULL AND close_date >= CURRENT_DATE - INTERVAL '{WINDOW_DAYS} days'),
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_on_market)
               FILTER (WHERE mls_status='Sold' AND days_on_market IS NOT NULL AND close_date >= CURRENT_DATE - INTERVAL '{WINDOW_DAYS} days')
      FROM raw_listings WHERE detected_area=%s;""", (AREA_SLUG,))
    n,price,dom=cur.fetchone(); c.close()
    return int(n or 0), (float(price) if price else None), (int(round(float(dom))) if dom else None)

def money_short(v):  return "$%.2fM"%(v/1e6) if v and v>=1e6 else ("$%s"%format(int(v),",") if v else "—")
def money_spoken(v):
    if not v: return "not available"
    return "%.2f million dollars"%(v/1e6) if v>=1e6 else "%d thousand dollars"%round(v/1000)

# ---- 2. avatar (HeyGen v3 transparent webm) ----
def heygen(url, method="GET", body=None):
    r=urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None)
    r.add_header("x-api-key",KEY); r.add_header("Content-Type","application/json")
    with urllib.request.urlopen(r, timeout=60) as resp: return json.loads(resp.read().decode())

def gen_avatar(script_text):
    body={"type":"avatar","avatar_id":AVATAR_ID,"voice_id":VOICE_ID,"script":script_text,
          "resolution":RESOLUTION,"aspect_ratio":"16:9","output_format":"webm","remove_background":True}
    vid=heygen("https://api.heygen.com/v3/videos","POST",body)["data"]["video_id"]
    print("avatar video_id",vid,"- polling")
    while True:
        d=heygen(f"https://api.heygen.com/v3/videos/{vid}")["data"]
        if d["status"]=="completed":
            out=WORK/"avatar.webm"; urllib.request.urlretrieve(d["video_url"], out); return out
        if d["status"]=="failed": sys.exit("avatar failed: "+str(d.get("failure_message")))
        time.sleep(8)

# ---- 3. data panel (PIL) ----
def build_panel(n, price, dom):
    from PIL import Image, ImageDraw, ImageFont
    W,Ht=480,620; img=Image.new("RGBA",(W,Ht),(0,0,0,0)); d=ImageDraw.Draw(img)
    fb="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; fr="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    F=lambda p,s:ImageFont.truetype(p,s)
    d.rounded_rectangle([0,0,W,Ht],radius=22,fill=NAVY); d.rectangle([0,0,8,Ht],fill=GOLD)
    P=40
    d.text((P,38),f"PAST {WINDOW_DAYS} DAYS  ·  {AREA_NAME.upper()}",font=F(fr,15),fill=GOLD)
    rows=[(str(n),"Homes Sold"),(money_short(price),"Median Sold Price"),(str(dom) if dom else "—","Median Days on Market")]
    y=92
    for val,lab in rows:
        d.text((P,y),val,font=F(fb,58),fill=WHITE); d.text((P,y+70),lab.upper(),font=F(fr,15),fill=MUTED); y+=140
    d.line([P,y+4,W-P,y+4],fill=(255,255,255,40),width=1)
    d.text((P,y+22),"THE ADAMSON GROUP",font=F(fb,17),fill=WHITE)
    d.text((P,y+48),"Ryan Adamson · Coldwell Banker",font=F(fr,14),fill=MUTED)
    out=WORK/"panel.png"; img.save(out); return out

# ---- 4. composite (ffmpeg) ----
def bbox(webm):
    from PIL import Image
    fr=WORK/"frame.png"
    subprocess.run(["ffmpeg","-y","-c:v","libvpx-vp9","-i",str(webm),"-frames:v","1",str(fr)],
                   check=True,capture_output=True)
    b=Image.open(fr).convert("RGBA").getbbox(); return b[0],b[1],b[2]-b[0],b[3]-b[1]

def composite(bg, webm, panel):
    lx,uy,cw,ch=bbox(webm)
    out=WORK/"market-minute.mp4"
    fc=(f"[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,eq=brightness=-0.05:saturation=1.05[bg];"
        f"[1:v]crop={cw}:{ch}:{lx}:{uy},scale=-1:{AVATAR_H}[av];"
        f"[bg][av]overlay=W-w-36:H-h-8:shortest=1[t1];"
        f"[t1][2:v]overlay=44:50[outv]")
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(bg),"-c:v","libvpx-vp9","-i",str(webm),"-i",str(panel),
        "-filter_complex",fc,"-map","[outv]","-map","1:a","-c:v","libx264","-pix_fmt","yuv420p","-crf","20",
        "-c:a","aac","-b:a","128k","-shortest",str(out)],check=True,capture_output=True)
    return out

def main():
    n,price,dom=fetch_stats()
    print(f"{AREA_NAME} past {WINDOW_DAYS}d: sold={n} median={money_short(price)} dom={dom}")
    if n==0: sys.exit("No sales in window — nothing to render.")
    script=(f"This week on {AREA_NAME}: {n} homes sold, median price {money_spoken(price)}, "
            f"and {dom} median days on market.")
    print("script:",script)
    webm=gen_avatar(script)
    panel=build_panel(n,price,dom)
    out=composite(ROOT/BG_IMAGE, webm, panel)
    print("DONE ->",out)

if __name__=="__main__": main()
