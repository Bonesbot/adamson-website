#!/usr/bin/env python3
"""
Adamson Group social video pipeline — raw footage -> branded, post-ready reel.

  intake (Drive) -> contact sheet -> [human/Claude: EDL + copy] -> HeyGen avatar
                 -> ffmpeg render (template-driven) -> QC frames -> export

All branding comes from templates/coastal-luxury.json (or another template).
Deterministic once the EDL + script text exist: re-runs are token-free and identical.

Usage:
  # 1. stage footage, then build a contact sheet to pick shots from
  python social_reel.py --footage <drive-file-id> --sheet-only

  # 2. full build
  python social_reel.py --footage <drive-file-id> --edl edl.json --avatar ryan \
      --preset ig-reel --hook "The amenity|no one can build." \
      --script "This is a Saturday on Sarasota Bay. ... Adamson F L dot com." \
      [--music track.m4a] [--no-avatar-render reuse.webm]

EDL JSON: list of shots, crop centers are % of frame width (9:16 window pans between them):
  [{"in": 4.0, "dur": 6.0, "panFromPct": 50, "panToPct": 59}, ...]

Requires: ffmpeg, pip install pillow. Env: HEYGEN_API_KEY (repo .env).
Proven end-to-end 2026-07-10 (DJI_0025.MP4 -> adamson-sandbar-reel-9x16.mp4).
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # repo root
WORK = Path(os.environ.get("REEL_WORK", "/tmp/vid")); IN=WORK/"in"; W=WORK/"work"; OUT=WORK/"out"
for p in (IN, W, OUT): p.mkdir(parents=True, exist_ok=True)

def sh(cmd, **kw): return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)
def ff(args): return sh(["ffmpeg","-v","error","-y"]+args)

def load_env():
    p = ROOT/".env"
    if p.exists():
        for ln in p.read_text().splitlines():
            if ln.strip() and not ln.startswith("#") and "=" in ln:
                k,v = ln.split("=",1); os.environ.setdefault(k.strip(), v.strip())

# ---------------------------------------------------------------- intake ----
def drive_download(file_id, dest):
    """Public/link-shared Drive file -> dest. Handles the virus-scan confirm page.
    Resumable: safe to re-run until complete."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    probe = W/"probe.html"
    sh(["curl","-sL",url,"-o",str(probe)])
    head = probe.read_bytes()[:200]
    if b"<html" in head.lower() or b"<!doctype" in head.lower():
        h = probe.read_text(errors="ignore")
        action = re.search(r'action="([^"]+)"', h).group(1)
        params = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', h))
        url = action + "?" + "&".join(f"{k}={v}" for k,v in params.items())
    # chunked resume loop (sandbox kills long processes; -C - resumes)
    for _ in range(120):
        r = subprocess.run(["curl","-sL","-C","-","--max-time","40",url,"-o",str(dest)])
        if r.returncode == 0: return dest
    raise RuntimeError("download did not complete")

def probe_duration(src):
    return float(sh(["ffprobe","-v","error","-show_entries","format=duration",
                     "-of","csv=p=0",str(src)]).stdout.strip())

def contact_sheet(src, n=24, cols=4):
    dur = probe_duration(src); step = dur/n
    for i in range(n):
        ff(["-ss",f"{i*step+0.5:.2f}","-i",str(src),"-frames:v","1",
            "-vf","scale=320:180",str(W/f"thumb{i:02d}.jpg")])
    ff(["-pattern_type","glob","-i",str(W/"thumb*.jpg"),
        "-filter_complex",f"tile={cols}x{n//cols}",str(OUT/"contact_sheet.jpg")])
    print(f"contact sheet -> {OUT/'contact_sheet.jpg'}  (duration {dur:.1f}s, ~{step:.2f}s/tile)")

# ---------------------------------------------------------------- avatar ----
def heygen(url, method="GET", body=None):
    r = urllib.request.Request(url, method=method,
                               data=json.dumps(body).encode() if body else None)
    r.add_header("x-api-key", os.environ["HEYGEN_API_KEY"])
    r.add_header("Content-Type","application/json")
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())

def render_avatar(tpl, who, script_text):
    av = tpl["avatars"][who]
    body = {"type":"avatar","avatar_id":av["look"],"voice_id":av["voice"],
            "script":script_text,"resolution":"720p","aspect_ratio":"16:9",
            "output_format":"webm","remove_background":True}
    vid = heygen("https://api.heygen.com/v3/videos","POST",body)["data"]["video_id"]
    print("heygen video_id", vid)
    while True:
        d = heygen(f"https://api.heygen.com/v3/videos/{vid}")["data"]
        if d["status"] == "completed":
            out = W/"avatar.webm"; urllib.request.urlretrieve(d["video_url"], out); return out
        if d["status"] == "failed": sys.exit("heygen failed: %s" % d.get("failure_message"))
        time.sleep(8)

# ------------------------------------------------------------ brand assets ----
def build_assets(tpl):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
    NAVY=tuple(tpl["colors"]["navy"]); TOP=tuple(tpl["colors"]["navyTop"])
    GOLD=tuple(tpl["colors"]["gold"]); D=tpl["bubble"]["diameter"]; C=tpl["bubble"]["ringCanvas"]; SS=4
    # white logo
    src = Image.open(ROOT/tpl["logo"]["source"]).convert("RGBA")
    if tpl["logo"]["invertToWhite"]:
        r,g,b,a = src.split()
        src = Image.merge("RGBA", tuple(ImageOps.invert(c) for c in (r,g,b))+(a,))
    src.save(W/"logo-white.png")
    # circle mask
    m = Image.new("L",(D*SS,D*SS),0); ImageDraw.Draw(m).ellipse([0,0,D*SS-1,D*SS-1],fill=255)
    m.resize((D,D),Image.LANCZOS).save(W/"circle_mask.png")
    # gold ring + soft shadow
    rw = tpl["bubble"]["ringWidth"]
    ring = Image.new("RGBA",(C*SS,C*SS),(0,0,0,0)); d = ImageDraw.Draw(ring)
    sh_ = Image.new("RGBA",(C*SS,C*SS),(0,0,0,0))
    ImageDraw.Draw(sh_).ellipse([6*SS,10*SS,(C-4)*SS,C*SS],fill=(0,0,0,110))
    ring.alpha_composite(sh_.filter(ImageFilter.GaussianBlur(6*SS)))
    d.ellipse([10*SS,10*SS,(C-10)*SS-1,(C-10)*SS-1],outline=GOLD+(255,),width=rw*SS)
    d.ellipse([16*SS,16*SS,(C-16)*SS-1,(C-16)*SS-1],outline=(255,255,255,90),width=SS)
    ring.resize((C,C),Image.LANCZOS).save(W/"ring.png")
    # end card
    ec = tpl["endcard"]; Wd,Ht = 1080,1920
    img = Image.new("RGB",(Wd,Ht),NAVY); dr = ImageDraw.Draw(img)
    for y in range(Ht):
        t=y/Ht; dr.line([(0,y),(Wd,y)],fill=tuple(int(TOP[i]+(NAVY[i]-TOP[i])*t) for i in range(3)))
    logo = Image.open(W/"logo-white.png"); LW = ec["logoWidth"]
    logo = logo.resize((LW,int(LW*logo.height/logo.width)),Image.LANCZOS)
    img.paste(logo,((Wd-LW)//2, ec["logoY"]),logo)
    play = ImageFont.truetype(str(ROOT/tpl["fonts"]["headline"]), ec["ctaFontsize"])
    body = lambda s: ImageFont.truetype(tpl["fonts"]["body"], s)
    y0 = ec["logoY"]+logo.height+70
    def center(txt,font,y,fill):
        w=dr.textlength(txt,font=font); dr.text(((Wd-w)/2,y),txt,font=font,fill=fill)
    center(ec["nameText"],body(44),y0,(255,255,255))
    center(ec["subText"],body(28),y0+70,(190,198,212))
    dr.line([(Wd/2-90,y0+150),(Wd/2+90,y0+150)],fill=GOLD,width=3)
    center(ec["ctaText"],play,y0+200,GOLD)
    center(ec["footerText"],body(26),y0+340,(180,190,205))
    img.save(W/"endcard.png")

# ---------------------------------------------------------------- render ----
def cut_segments(src, edl, tpl, size):
    outW,outH = size
    segs=[]
    for i,s in enumerate(edl):
        seg = W/f"seg{i}.mp4"
        # scale to output height, pan a outW-wide crop between the two centers
        sw = f"scale=-2:{outH}"
        x0 = f"(iw*{s['panFromPct']}/100-{outW}/2)"; x1 = f"(iw*{s['panToPct']}/100-{outW}/2)"
        crop = f"crop={outW}:{outH}:'max(0,{x0}+({x1}-{x0})*t/{s['dur']})':0"
        ff(["-ss",str(s["in"]),"-t",str(s["dur"]),"-i",str(src),
            "-vf",f"{sw},{crop},{tpl['grade']},fps=30","-an",
            "-c:v","libx264","-preset","veryfast","-crf","16",str(seg)])
        segs.append((seg,s["dur"]))
    return segs

def assemble(segs, tpl, total_endcard):
    ec_d = tpl["endcard"]["durationSec"]; xf = tpl["transitions"]["durationSec"]
    ff(["-loop","1","-i",str(W/"endcard.png"),"-t",str(ec_d),
        "-vf","fps=30,format=yuv420p","-c:v","libx264","-preset","veryfast","-crf","16",
        str(W/"seg_end.mp4")])
    files=[s for s,_ in segs]+[W/"seg_end.mp4"]; durs=[d for _,d in segs]+[ec_d]
    inputs=[]; [inputs.extend(["-i",str(f)]) for f in files]
    fc=[]; cur="[0]"; t=durs[0]
    for i in range(1,len(files)):
        xd = tpl["endcard"]["xfadeDur"] if i==len(files)-1 else xf
        out=f"[x{i}]"; fc.append(f"{cur}[{i}]xfade=transition=fade:duration={xd}:offset={t-xd}{out}")
        cur=out; t=t-xd+durs[i]
    ff(inputs+["-filter_complex",";".join(fc),"-map",cur.strip("[]").join(["[","]"]),
        "-c:v","libx264","-preset","veryfast","-crf","16",str(W/"base.mp4")])
    return t  # total duration

def finish(tpl, total, hook, avatar_webm, music, out_name):
    b=tpl["bubble"]; hk=tpl["hook"]; D=b["diameter"]; start=b["startAt"]; fd=b["fadeDur"]
    av_dur = probe_duration(avatar_webm) if avatar_webm else 0
    av_end = start+av_dur
    body_end = total - tpl["endcard"]["durationSec"] - tpl["endcard"]["xfadeDur"] + 0.2
    fin=[ "-i",str(W/"base.mp4") ]
    fc=[]; vin="[0:v]"; aidx=None
    if avatar_webm:
        fin += ["-c:v","libvpx-vp9","-i",str(avatar_webm)]
        fin += ["-i",str(W/"circle_mask.png"),"-loop","1","-t",str(total),"-i",str(W/"ring.png")]
        fc += [f"[1:v]crop=402:402:0:{b['cropSquareY']},scale={D}:{D},setpts=PTS+{start}/TB[avs]",
               f"[2:v]format=gray,scale={D}:{D}[msk]",
               f"[avs][msk]alphamerge,fade=t=in:st={start}:d={fd}:alpha=1,"
               f"fade=t=out:st={av_end-0.45:.2f}:d=0.45:alpha=1[bub]",
               f"[3:v]format=rgba,fade=t=in:st={start}:d={fd}:alpha=1,"
               f"fade=t=out:st={av_end-0.45:.2f}:d=0.45:alpha=1[rng]",
               f"{vin}[bub]overlay={b['position'][0]+10}:{b['position'][1]+10}:eof_action=pass[t1]",
               f"[t1][rng]overlay={b['position'][0]}:{b['position'][1]}[t2]"]
        vin="[t2]"; aidx=1
        wm_in = 4
    else:
        wm_in = 1
    fin += ["-i",str(W/"logo-white.png")]
    if hook:
        l1,l2 = (hook.split("|")+[""])[:2]
        def dt(txt,y,t0):
            a=(f"if(lt(t,{t0}),0,if(lt(t,{t0+hk['fadeInDur']}),(t-{t0})/{hk['fadeInDur']},"
               f"if(lt(t,{hk['fadeOutAt']}),1,if(lt(t,{hk['fadeOutAt']+hk['fadeOutDur']}),"
               f"({hk['fadeOutAt']+hk['fadeOutDur']}-t)/{hk['fadeOutDur']},0))))")
            return (f"drawtext=fontfile={ROOT/tpl['fonts']['headline']}:text='{txt}':"
                    f"fontsize={hk['fontsize']}:fontcolor=white:shadowcolor=black@{hk['shadow'][2]}:"
                    f"shadowx={hk['shadow'][0]}:shadowy={hk['shadow'][1]}:x=(w-text_w)/2:y={y}:alpha='{a}'")
        fc.append(f"{vin}{dt(l1,hk['line1Y'],hk['fadeInAt'])},{dt(l2,hk['line2Y'],hk['fadeInAt']+0.2)}[t3]")
        vin="[t3]"
    wmk=tpl["watermark"]
    fc.append(f"[{wm_in}:v]scale={wmk['width']}:-1,format=rgba,colorchannelmixer=aa={wmk['opacity']}[wm]")
    fc.append(f"{vin}[wm]overlay=W-w-{wmk['margin'][0]}:{wmk['margin'][1]}:enable='lt(t,{body_end})',format=yuv420p[vout]")
    # audio
    amaps=[]
    if aidx is not None:
        fc.append(f"[{aidx}:a]adelay={int(start*1000)}|{int(start*1000)},apad,atrim=0:{total},"
                  f"afade=t=out:st={total-tpl['audio']['finalFadeOutSec']}:d={tpl['audio']['finalFadeOutSec']}[voice]")
        alab="[voice]"
        if music:
            fin+=["-i",str(music)]
            mi=len([x for x in fin if x=="-i"])-1
            fc.append(f"[{mi}:a]volume={tpl['audio']['musicDuckDb']}dB,atrim=0:{total}[mus]")
            fc.append(f"[voice][mus]amix=inputs=2:duration=first[aout]"); alab="[aout]"
        amaps=["-map",alab]
    out=OUT/out_name
    ff(fin+["-filter_complex",";".join(fc),"-map","[vout]"]+amaps+
       ["-c:v","libx264","-preset","medium","-crf","18","-c:a","aac","-b:a","160k",
        "-movflags","+faststart","-t",str(total),str(out)])
    print("DONE ->",out)
    return out

def qc(out):
    for t in (1.5, 5, 9, 14, 18, 21):
        ff(["-ss",str(t),"-i",str(out),"-frames:v","1","-vf","scale=270:480",str(W/f"chk_{t}.jpg")])
    print("QC frames in", W, "- review before posting. volumedetect:")
    r=subprocess.run(["ffmpeg","-i",str(out),"-af","volumedetect","-f","null","-"],
                     capture_output=True,text=True)
    print("\n".join(l for l in r.stderr.splitlines() if "volume" in l))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--footage",required=True,help="Drive file id OR local path")
    ap.add_argument("--template",default=str(Path(__file__).parent/"templates/coastal-luxury.json"))
    ap.add_argument("--edl"); ap.add_argument("--sheet-only",action="store_true")
    ap.add_argument("--avatar",choices=["ryan","kelli","none"],default="none")
    ap.add_argument("--script",default=""); ap.add_argument("--hook",default="")
    ap.add_argument("--music"); ap.add_argument("--preset",default="ig-reel")
    ap.add_argument("--no-avatar-render",help="reuse an existing transparent webm")
    ap.add_argument("--out",default="reel.mp4")
    a=ap.parse_args(); load_env()
    tpl=json.load(open(a.template))
    src = Path(a.footage) if Path(a.footage).exists() else drive_download(a.footage, IN/"footage.mp4")
    if a.sheet_only: contact_sheet(src); return
    size=tpl["presets"][a.preset]["size"]
    edl=json.load(open(a.edl))
    build_assets(tpl)
    webm=None
    if a.no_avatar_render: webm=Path(a.no_avatar_render)
    elif a.avatar!="none":
        assert a.script, "--script required for avatar"
        webm=render_avatar(tpl,a.avatar,a.script)
    segs=cut_segments(src,edl,tpl,size)
    total=assemble(segs,tpl,tpl["endcard"]["durationSec"])
    out=finish(tpl,total,a.hook,webm,a.music,a.out)
    qc(out)

if __name__=="__main__": main()
