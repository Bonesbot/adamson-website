"""St. Armands Circle walking-map handout (5.5 x 8.5 in, two-sided) for floor time.

Front: a real plan of the Circle drawn from OpenStreetMap footprints/roads (ODbL), rotated so
John Ringling Blvd toward Lido Beach points up (matches the view from the CB office window),
quadrants tinted in the lamppost banner colours, every restaurant/sweet shop from SRQmap's
St. Armands layer numbered, Ryan's picks starred, and a QR to adamsonfl.com/circle.
Back: listing slots, text line, sign-up, contact strip.

Built to be re-edited in Adobe Express / Canva: live text in Playfair Display, Montserrat and
Inter (all in both apps' font libraries), with only the map, the phone mockup and the QR
flattened to 300-dpi PNGs. Page is 5.75 x 8.75 in (5.5 x 8.5 trim + 0.125 in bleed) with
all text inside a 0.25 in safe margin.

Usage (from repo root):
    python3 scripts/handout/build_stac_handout.py scripts/handout/data/stac_osm_vec.json <out_dir>
Produces <out_dir>/stac_handout_bleed.pdf, stac_handout_trim.pdf and assets/*.png.
"""
import json, math, sys, os, re, subprocess
import segno

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VEC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
vec = json.load(open(VEC))
pins = [p for p in json.load(open(f"{ROOT}/src/data/srqmap-pins.json")) if p.get("place") == "stac" and p.get("group") == "dining"]

# ---------------- geometry ----------------
C = (27.3184, -82.5775)                       # map centre (park)
THETA = math.radians(127)                     # rotate so bearing 233 (John Ringling -> Lido) is up
S = 0.80                                      # pt per metre
MW, MH = 356, 262                             # map box (pt)
def m(lat, lng):                              # lat/lng -> metres east/north of centre
    return ((lng - C[1]) * math.cos(math.radians(C[0])) * 111320, (lat - C[0]) * 111320)
def scr(lat, lng):                            # -> map-box px (origin top-left)
    x, y = m(lat, lng)
    sx = x * math.cos(THETA) + y * math.sin(THETA)
    sy = x * math.sin(THETA) - y * math.cos(THETA)
    return (MW / 2 - 4 + sx * S, MH / 2 - 19 + sy * S)
def bearing(lat, lng):
    x, y = m(lat, lng); return (math.degrees(math.atan2(x, y)) + 360) % 360
def poly(pts): return " ".join(f"{x:.1f},{y:.1f}" for x, y in (scr(*p) for p in pts))
def centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

# quadrants are the sectors between the two boulevards (John Ringling ~60/240, Presidents ~345/165)
def quadrant(b):
    if 345 <= b or b < 60: return "GOLD"
    if 60 <= b < 165: return "AQUA"
    if 165 <= b < 240: return "PURPLE"
    return "PINK"
Q = {  # banner colours, pulled toward the brand's soft coastal palette
    "GOLD":   dict(fill="#D9B968", ink="#8A6A1E", label="Gold"),
    "PINK":   dict(fill="#E39AAA", ink="#9A4458", label="Pink"),
    "AQUA":   dict(fill="#7CC4C4", ink="#1E6E6E", label="Aqua"),
    "PURPLE": dict(fill="#A896C6", ink="#55407A", label="Purple"),
}
NAVY, GOLD, CREAM, SAND, INK = "#0A2A40", "#C9A961", "#F8F4EB", "#EBE2D0", "#1F2E38"
WATER, PARK, ROAD, ROADLINE, HOUSE = "#CFE1E8", "#CDE0C5", "#FFFFFF", "#D8CFBE", "#E6DCC8"

# ---------------- restaurants (numbered, grouped by quadrant) ----------------
PICKS = {"Columbia Restaurant", "Venezia Italian Restaurant", "Blu Kouzina", "Green Zebra (St Armands)"}
SHORT = {"Nonno Umberto Italian Seafood & Steakhouse": "Nonno Umberto", "Tommy Bahama Restaurant & Bar": "Tommy Bahama Restaurant",
         "Big Olaf Creamery (St. Armands)": "Big Olaf Creamery", "Kilwins Chocolates & Ice Cream": "Kilwins",
         "Green Zebra (St Armands)": "Green Zebra Café", "Pinchers (opening late 2026)": "Pinchers (opening late 2026)",
         "Ephesus Mediterranean Delights": "Ephesus Mediterranean", "I Love Candy & Ice Cream": "I Love Candy",
         "Cafe on St Armands": "Café on St. Armands", "Venezia Italian Restaurant": "Venezia", "Lynches Pub & Grub": "Lynches Pub"}
def addr_short(a):
    a = a.split(",")[0]
    return (a.replace("St Armands Cir", "St. Armands Cir").replace("John Ringling Blvd", "J. Ringling Blvd")
             .replace("Blvd of the Presidents", "Blvd of Presidents").replace("N Washington Dr", "N. Washington Dr"))
for p in pins:
    p["_q"] = quadrant(bearing(p["lat"], p["lng"]))
    p["_short"] = SHORT.get(p["name"], p["name"])
    p["_sweet"] = bool(re.search(r"ice cream|gelato|chocolate|candy|praline|coffee", p.get("food_style", ""), re.I))
order = ["GOLD", "PINK", "AQUA", "PURPLE"]   # legend order (clockwise from the office)
pins.sort(key=lambda p: (order.index(p["_q"]), p["_sweet"], p["_short"].lower()))
for i, p in enumerate(pins, 1): p["_n"] = i

# ---------------- SVG map ----------------
svg = []
svg.append(f'<rect width="{MW}" height="{MH}" fill="{CREAM}"/>')
for w in vec["water"]:
    if len(w["pts"]) > 3 and w["pts"][0] == w["pts"][-1]: svg.append(f'<polygon points="{poly(w["pts"])}" fill="{WATER}"/>')
for w in vec["parks"]:
    if len(w["pts"]) > 3: svg.append(f'<polygon points="{poly(w["pts"])}" fill="{PARK}"/>')
for w in vec["parking"]:
    if len(w["pts"]) > 3:
        svg.append(f'<polygon points="{poly(w["pts"])}" fill="#E8E4DB" stroke="{ROADLINE}" stroke-width=".6"/>')
        cx, cy = scr(*centroid(w["pts"]))
        if 10 < cx < MW - 10 and 10 < cy < MH - 10:
            svg.append(f'<text x="{cx:.1f}" y="{cy + 3:.1f}" font-family="Montserrat" font-weight="700" font-size="8" fill="#6B7A86" text-anchor="middle">P</text>')
# buildings: commercial ring tinted by quadrant, houses as soft sand
for b in vec["buildings"]:
    if len(b["pts"]) < 4: continue
    la, lo = centroid(b["pts"]); r = math.hypot(*m(la, lo))
    kind = b["tags"].get("building", "yes")
    if kind in ("house", "residential", "apartments", "garage", "shed") or (kind == "yes" and r > 215):
        svg.append(f'<polygon points="{poly(b["pts"])}" fill="{HOUSE}"/>')
    elif kind == "parking":
        svg.append(f'<polygon points="{poly(b["pts"])}" fill="#DDD8CE" stroke="{ROADLINE}" stroke-width=".6"/>')
        cx, cy = scr(la, lo)
        svg.append(f'<text x="{cx:.1f}" y="{cy + 3:.1f}" font-family="Montserrat" font-weight="700" font-size="8" fill="#6B7A86" text-anchor="middle">P</text>')
    elif r < 215:
        q = Q[quadrant(bearing(la, lo))]
        svg.append(f'<polygon points="{poly(b["pts"])}" fill="{q["fill"]}" fill-opacity=".55" stroke="{q["ink"]}" stroke-opacity=".35" stroke-width=".5"/>')
    else:
        svg.append(f'<polygon points="{poly(b["pts"])}" fill="#E1D8C6"/>')
# roads: casing then fill
def road_w(t):
    h = t.get("highway", "")
    if h in ("primary", "secondary", "tertiary", "primary_link", "secondary_link"): return 11
    if h in ("residential", "unclassified", "living_street"): return 6
    if h == "service": return 2.5
    return 0
road_lines = []
for r in vec["roads"]:
    w = road_w(r["tags"])
    if not w: continue
    road_lines.append((w, poly(r["pts"]), r["tags"]))
for w, pts, t in road_lines:
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{ROADLINE}" stroke-width="{w + 1.4}" stroke-linecap="round" stroke-linejoin="round"/>')
for w, pts, t in road_lines:
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{ROAD}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')
# road-name labels along the longest in-box segment of each named street
def label_roads():
    best = {}
    for r in vec["roads"]:
        n = r["tags"].get("name")
        if not n or road_w(r["tags"]) < 6: continue
        pts = [scr(*p) for p in r["pts"]]
        for a, b in zip(pts, pts[1:]):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if not (22 < mx < MW - 22 and 22 < my < MH - 22): continue
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L > best.get(n, (0,))[0]: best[n] = (L, mx, my, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
    out = []
    for n, (L, mx, my, ang) in best.items():
        if L < 38: continue
        if ang > 90: ang -= 180
        if ang < -90: ang += 180
        short = (n.replace("Boulevard", "Blvd").replace("Drive", "Dr").replace("North ", "N. ").replace("South ", "S. ")
                  .replace("Benjamin Franklin", "Ben Franklin"))
        big = road_w({"highway": "primary"}) and n in ("John Ringling Boulevard", "Boulevard of the Presidents", "South Boulevard of the Presidents", "North Boulevard of the Presidents")
        out.append(f'<text transform="translate({mx:.1f},{my:.1f}) rotate({ang:.1f})" font-family="Inter" font-size="{6.2 if big else 5.4}" font-weight="{600 if big else 500}" fill="#6E7F8C" text-anchor="middle" dy="2" letter-spacing=".04em">{short.upper()}</text>')
    return out
svg += label_roads()
# restaurant markers (nudged apart where storefronts are shoulder to shoulder)
MK = [[*scr(p["lat"], p["lng"])] for p in pins]
for _ in range(60):
    for i in range(len(MK)):
        for j in range(i + 1, len(MK)):
            dx, dy = MK[j][0] - MK[i][0], MK[j][1] - MK[i][1]; d = math.hypot(dx, dy) or .01
            if d < 13.5:
                push = (13.5 - d) / 2; ux, uy = dx / d, dy / d
                MK[i][0] -= ux * push; MK[i][1] -= uy * push; MK[j][0] += ux * push; MK[j][1] += uy * push
for p, (x, y) in zip(pins, MK):
    q = Q[p["_q"]]; star = p["name"] in PICKS
    if star: svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.6" fill="none" stroke="{GOLD}" stroke-width="1.6"/>')
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.2" fill="{q["ink"]}" stroke="#fff" stroke-width="1.3"/>')
    svg.append(f'<text x="{x:.1f}" y="{y + 2.5:.1f}" font-family="Montserrat" font-weight="700" font-size="{6.8 if p["_n"] < 10 else 6.1}" fill="#fff" text-anchor="middle">{p["_n"]}</text>')
# compass (soft)
nx, ny, na = 24, MH - 24, 127
svg.append(f'<g transform="translate({nx},{ny})"><circle r="12" fill="#fff" fill-opacity=".8" stroke="{ROADLINE}" stroke-width=".8"/>'
           f'<g transform="rotate({na})"><polygon points="0,-9 3,0 -3,0" fill="#6E7F8C"/><polygon points="0,9 3,0 -3,0" fill="#CFC9BC"/>'
           f'<text y="-11.5" font-family="Montserrat" font-weight="700" font-size="5.5" fill="#6E7F8C" text-anchor="middle">N</text></g></g>')
MAP_SVG = f'<svg viewBox="0 0 {MW} {MH}" width="{MW}" height="{MH}" xmlns="http://www.w3.org/2000/svg">{"".join(svg)}</svg>'

# ---------------- flattened assets (300 dpi PNG) ----------------
ASSETS = f"{OUT}/assets"; os.makedirs(ASSETS, exist_ok=True)
import shutil as _sh
FONT_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
if os.path.exists(f"{OUT}/fonts"): _sh.rmtree(f"{OUT}/fonts")
_sh.copytree(FONT_SRC, f"{OUT}/fonts")
FONT_CSS = open(f"{FONT_SRC}/fonts.css").read()
open(f"{OUT}/_map.html", "w").write(f'<!doctype html><html><head><meta charset="utf-8"><style>{FONT_CSS} body{{margin:0;background:{CREAM}}}svg{{display:block}}</style></head><body>{MAP_SVG}</body></html>')
QR_URL = "https://adamsonfl.com/circle"
segno.make(QR_URL, error="m").save(f"{ASSETS}/qr-adamsonfl-circle.png", scale=24, border=2, dark=NAVY, light="#FFFFFF")
NC_URL = "https://adamsonfl.com/new-construction/?utm_source=handout&utm_medium=print&utm_campaign=stac-map"
segno.make(NC_URL, error="m").save(f"{ASSETS}/qr-new-construction.png", scale=24, border=2, dark=NAVY, light="#FFFFFF")
for _img in ("mira-mar-hero.jpg", "ritz-carlton-residences-hero.jpg", "rosewood-residences-lido-hero.jpg"):
    _sh.copy(f"{ROOT}/public/images/new-construction/{_img}", f"{ASSETS}/{_img}")

PHONE_W, PHONE_H = 390, 844
render = f"""
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        # map @ 300 dpi (pt -> px is 300/72)
        pg = await b.new_page(viewport={{'width': {MW}, 'height': {MH}}}, device_scale_factor=300/72)
        await pg.goto('file://{OUT}/_map.html', wait_until='networkidle'); await pg.evaluate('document.fonts.ready'); await pg.wait_for_timeout(500)
        await pg.screenshot(path='{ASSETS}/map-st-armands-circle.png', clip={{'x':0,'y':0,'width':{MW},'height':{MH}}})
        # live /circle page as a phone screen
        ctx = await b.new_context(viewport={{'width': {PHONE_W}, 'height': {PHONE_H}}}, device_scale_factor=3, is_mobile=True, has_touch=True,
                                  user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
        pg2 = await ctx.new_page()
        await pg2.goto('https://adamsonfl.com/circle', wait_until='networkidle'); await pg2.wait_for_timeout(2500)
        await pg2.screenshot(path='{ASSETS}/_screen.png')
        await b.close()
asyncio.run(main())
"""
subprocess.run([sys.executable, "-c", render], check=True, env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")})

# phone frame around the screenshot
from PIL import Image, ImageDraw
scr_img = Image.open(f"{ASSETS}/_screen.png").convert("RGBA")
sw, sh = scr_img.size                                   # 1170 x 2532
bez = 54; r_outer = 190; r_inner = 150
W, H = sw + 2 * bez, sh + 2 * bez
frame = Image.new("RGBA", (W + 80, H + 80), (0, 0, 0, 0))
d = ImageDraw.Draw(frame)
# soft shadow
for i, a in ((36, 18), (28, 26), (20, 34)):
    d.rounded_rectangle((40 - i // 2, 40 + 18 - i // 2, 40 + W + i // 2, 40 + 18 + H + i // 2), r_outer + i, fill=(10, 42, 64, a))
d.rounded_rectangle((40, 40, 40 + W, 40 + H), r_outer, fill=(16, 24, 32, 255))
d.rounded_rectangle((40 + 6, 40 + 6, 40 + W - 6, 40 + H - 6), r_outer - 6, outline=(70, 80, 90, 255), width=3)
mask = Image.new("L", (sw, sh), 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw, sh), r_inner, fill=255)
frame.paste(scr_img, (40 + bez, 40 + bez), mask)
# dynamic island
d.rounded_rectangle((40 + W // 2 - 190, 40 + bez + 30, 40 + W // 2 + 190, 40 + bez + 30 + 100), 50, fill=(16, 24, 32, 255))
frame.save(f"{ASSETS}/phone-srqmap-circle.png")
os.remove(f"{ASSETS}/_screen.png")
import shutil; shutil.copy(f"{ROOT}/public/images/logos/adamson-group-black.png", f"{ASSETS}/adamson-group-logo.png")

# ---------------- legend ----------------
def legend_html():
    cols = ["", ""]; half = math.ceil(len(pins) / 2)
    for i, p in enumerate(pins):
        q = Q[p["_q"]]
        star = ' <span class="star">★</span>' if p["name"] in PICKS else ""
        tag = ' <span class="sweet">sweets</span>' if p["_sweet"] else ""
        cols[0 if i < half else 1] += (f'<div class="row"><span class="n" style="background:{q["ink"]}">{p["_n"]}</span>'
                                      f'<span class="nm">{p["_short"]}{star}{tag}</span><span class="ad">{addr_short(p["address"])}</span></div>')
    return f'<div class="col">{cols[0]}</div><div class="col">{cols[1]}</div>'

# ---------------- page (5.75 x 8.75 with bleed; safe area 0.25 in inside trim) ----------------
BLEED, SAFE = 9, 18           # pt
PAD = BLEED + SAFE            # 27pt from page edge to content
CSS = f"""
@page {{ size: 5.75in 8.75in; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: Inter, sans-serif; color:{INK}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.page {{ width:5.75in; height:8.75in; padding:{PAD}pt; background:{CREAM}; position:relative; overflow:hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
h1 {{ font-family:'Playfair Display', serif; font-weight:600; font-size:23pt; margin:0; color:{NAVY}; line-height:1; }}
.kicker {{ font-family: Montserrat, sans-serif; font-weight:700; font-size:6.8pt; color:{GOLD}; text-transform:uppercase; margin:0 0 4pt; }}
.sub {{ font-size:7.6pt; color:#55656F; margin:4pt 0 0; }}
.head {{ display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:6pt; }}
.est {{ font-family:'Playfair Display', serif; font-style:italic; font-size:8pt; color:#7A6A45; text-align:right; line-height:1.25; }}
.map {{ display:block; width:360pt; height:{round(360 * MH / MW)}pt; border-radius:10pt; }}
.qlegend {{ display:flex; gap:9pt; margin:5pt 0 5pt; font-family:Montserrat, sans-serif; font-weight:600; font-size:6.3pt; text-transform:uppercase; color:#55656F; align-items:center; }}
.qlegend i {{ display:inline-block; width:8pt; height:8pt; border-radius:2pt; margin-right:3pt; vertical-align:-1pt; }}
.qlegend .hint {{ margin-left:auto; text-transform:none; font-family:Inter; font-weight:400; font-size:6.4pt; }}
.bottom {{ display:flex; gap:9pt; align-items:stretch; }}
.legend {{ flex:1; display:flex; gap:7pt; }}
.col {{ flex:1; min-width:0; }}
.row {{ display:grid; grid-template-columns:11pt 1fr; column-gap:3pt; align-items:baseline; font-size:6.2pt; line-height:1.08; padding:.5pt 0; border-bottom:.4pt solid #E6DFD0; }}
.n {{ color:#fff; font-family:Montserrat; font-weight:700; font-size:5.6pt; width:10pt; height:10pt; border-radius:50%; display:inline-grid; place-items:center; align-self:center; }}
.nm {{ font-weight:600; color:{NAVY}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.ad {{ grid-column:2; font-size:5.2pt; color:#7B8993; margin-top:-1pt; }}
.star {{ color:{GOLD}; }}
.sweet {{ font-size:4.8pt; color:#9A4458; font-weight:600; text-transform:uppercase; margin-left:2pt; }}
.promo {{ width:118pt; flex:none; background:#fff; border:1pt solid {GOLD}; border-radius:9pt; padding:7pt 7pt 6pt; display:flex; flex-direction:column; align-items:center; }}
.promo .t {{ font-family:Montserrat; font-weight:700; font-size:6.4pt; color:{NAVY}; text-transform:uppercase; margin:0 0 5pt; text-align:center; }}
.promo .pair {{ display:flex; gap:6pt; align-items:flex-end; }}
.promo .phone {{ width:58pt; height:auto; display:block; }}
.promo .qrbox {{ display:flex; flex-direction:column; align-items:center; gap:3pt; }}
.promo .qr {{ width:46pt; height:46pt; display:block; }}
.promo .scan {{ font-family:Montserrat; font-weight:700; font-size:5.6pt; color:{NAVY}; text-transform:uppercase; }}
.promo .d {{ font-size:5.9pt; line-height:1.3; color:#55656F; margin:5pt 0 0; text-align:center; }}
.promo .u {{ font-family:Montserrat; font-weight:700; font-size:6.4pt; color:{NAVY}; margin-top:3pt; }}
.foot {{ position:absolute; left:{PAD}pt; right:{PAD}pt; bottom:{PAD - 8}pt; display:flex; justify-content:space-between; font-size:5.2pt; color:#8E9AA3; }}
/* back */
.back h2 {{ font-family:'Playfair Display', serif; font-weight:600; font-size:15.5pt; color:{NAVY}; margin:0 0 3pt; line-height:1.1; }}
.lead {{ font-size:7.8pt; line-height:1.4; color:#3B4A55; margin:0 0 8pt; }}
.slots {{ display:grid; grid-template-columns:repeat(3,1fr); gap:7pt; margin-bottom:8pt; }}
.slot {{ background:#fff; border:1pt solid #E4DCCB; border-radius:8pt; overflow:hidden; }}
.slot .ph {{ height:50pt; background-size:cover; background-position:center; }}
.slot .st {{ display:inline-block; font-family:Montserrat; font-weight:700; font-size:5pt; text-transform:uppercase; color:#fff; background:{NAVY}; border-radius:999pt; padding:2pt 5pt; margin:5pt 0 0 5pt; }}
.nc-head {{ display:flex; align-items:center; gap:9pt; margin:0 0 6pt; }}
.nc-head img {{ width:40pt; height:40pt; flex:none; }}
.nc-head .u {{ font-family:Montserrat; font-weight:700; font-size:6.4pt; color:{NAVY}; }}
.credit {{ font-size:4.8pt; color:#9AA5AD; margin:-5pt 0 7pt; }}
.slot .b {{ padding:5pt 6pt 6pt; }}
.slot .p {{ font-family:Montserrat; font-weight:700; font-size:7.2pt; color:{NAVY}; line-height:1.15; }}
.slot .a {{ font-size:6pt; color:#55656F; margin-top:2pt; line-height:1.3; }}
.slot .f {{ font-size:6pt; color:#7B8993; margin-top:2pt; }}
.band {{ background:{NAVY}; color:#fff; border-radius:10pt; padding:9pt 13pt; margin-bottom:7pt; display:flex; align-items:center; gap:12pt; }}
.band .big {{ font-family:'Playfair Display', serif; font-size:13.5pt; line-height:1.12; }}
.band .num {{ font-family:Montserrat; font-weight:700; font-size:15pt; color:{GOLD}; white-space:nowrap; }}
.band .s {{ font-size:6.8pt; color:#C8D3DB; margin-top:3pt; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:7pt; margin-bottom:7pt; }}
.card {{ background:#fff; border:1pt solid #E4DCCB; border-radius:9pt; padding:7pt 9pt; }}
.card h3 {{ font-family:Montserrat; font-weight:700; font-size:7pt; text-transform:uppercase; color:{GOLD}; margin:0 0 4pt; }}
.card p {{ font-size:6.9pt; line-height:1.38; margin:0; color:#3B4A55; }}
.line {{ border-bottom:.7pt solid #B9C2C9; height:9pt; margin-top:4pt; }}
.contact {{ display:flex; align-items:center; gap:10pt; border-top:1pt solid {GOLD}; padding-top:8pt; }}
.contact img {{ height:30pt; }}
.contact .nm2 {{ font-family:'Playfair Display', serif; font-size:12.5pt; color:{NAVY}; line-height:1.05; }}
.contact .r {{ font-size:6.6pt; color:#55656F; line-height:1.4; }}
.contact .ph2 {{ margin-left:auto; text-align:right; font-family:Montserrat; font-weight:700; font-size:10pt; color:{NAVY}; }}
.contact .ph2 small {{ display:block; font-family:Inter; font-weight:400; font-size:6.2pt; color:#55656F; }}
"""

front = f"""
<div class="page">
  <div class="head">
    <div><p class="kicker">A walking map · Lido Key, Sarasota</p><h1>St. Armands Circle</h1>
      <p class="sub">Where to eat on the Circle, by quadrant · Lido Beach is up, as you see it from our door</p></div>
    <div class="est">est. 1926<br>by John Ringling</div>
  </div>
  <img class="map" src="assets/map-st-armands-circle.png" alt="Map of St. Armands Circle">
  <div class="qlegend">
    <span><i style="background:{Q['GOLD']['fill']}"></i>Gold</span><span><i style="background:{Q['PINK']['fill']}"></i>Pink</span>
    <span><i style="background:{Q['AQUA']['fill']}"></i>Aqua</span><span><i style="background:{Q['PURPLE']['fill']}"></i>Purple</span>
    <span class="hint">Lamppost banner colours &nbsp;·&nbsp; <span style="color:{GOLD}">★</span> Ryan's picks &nbsp;·&nbsp; CB = our office</span>
  </div>
  <div class="bottom">
    <div class="legend">{legend_html()}</div>
    <div class="promo"><p class="t">The live map, on your phone</p>
      <div class="pair"><img class="phone" src="assets/phone-srqmap-circle.png" alt=""><div class="qrbox"><img class="qr" src="assets/qr-adamsonfl-circle.png" alt="QR code"><span class="scan">Scan me</span></div></div>
      <p class="d">Every spot here with Ryan's take, hours and directions, plus beaches, golf and this week's events.</p><p class="u">adamsonfl.com/circle</p></div>
  </div>
  <div class="foot"><span>Map data © OpenStreetMap contributors (ODbL). Directory checked Oct 2026; the Circle changes, call ahead.</span><span>Ryan Adamson, PA · Coldwell Banker Realty · (941) 713-9234</span></div>
</div>"""

back = f"""
<div class="page back">
  <p class="kicker">From the office at 423, Gold quadrant</p>
  <h2>The next generation of Sarasota towers is rising now.</h2>
  <div class="nc-head"><p class="lead" style="margin:0">I'm Ryan Adamson, the agent in the Coldwell Banker window on the Circle. Sarasota is in the middle of its biggest luxury-condo cycle in a generation: beachfront on Lido, bayfront at The Quay, Palm Avenue downtown. Three worth knowing about, and a page that keeps you current on all of them:<br><span class="u">adamsonfl.com/new-construction</span></p><img src="assets/qr-new-construction.png" alt="QR code"></div>
  <div class="slots">
    <div class="slot"><div class="ph" style="background-image:url('assets/rosewood-residences-lido-hero.jpg')"><span class="st">Move-ins 2026</span></div><div class="b"><div class="p">Rosewood Residences Lido Key</div><div class="a">65 private beachfront residences on Lido, a 10-minute walk from this Circle. Rosewood's first stand-alone residential project.</div></div></div>
    <div class="slot"><div class="ph" style="background-image:url('assets/ritz-carlton-residences-hero.jpg')"><span class="st">Completing late 2026</span></div><div class="b"><div class="p">The Ritz-Carlton Residences, Sarasota Bay</div><div class="a">78 flow-through residences at The Quay: bay on one side, skyline on the other, full Ritz-Carlton service.</div></div></div>
    <div class="slot"><div class="ph" style="background-image:url('assets/mira-mar-hero.jpg')"><span class="st">Delivery 2028</span></div><div class="b"><div class="p">Mira Mar Residences</div><div class="a">70 estate-scale residences in two towers behind the restored 1922 Mira Mar on Palm Avenue, downtown.</div></div></div>
  </div>
  <p class="credit">Renderings courtesy of The Ronto Group, Kolter Urban and Seaward Development. Pricing, availability and delivery change; ask for the current sheet.</p>
  <div class="band"><div><div class="big">Text me anything about Sarasota.</div><div class="s">Prices on Longboat, which buildings allow rentals, where to have dinner tonight, what the Gulf is doing to insurance. A real answer from a local, not a bot.</div></div><div class="num">941-XXX-XXXX</div></div>
  <div class="two">
    <div class="card"><h3>Stay current on new condo releases</h3><p>New releases, price moves and delivery dates at these towers, plus island listings that never hit the portals and a short monthly market note. No spam, unsubscribe any time.</p><div class="line"></div><p style="font-size:5.6pt;color:#8E9AA3;margin-top:2pt">name &amp; email or cell · hand it back to me, or text UPDATES to the number above</p></div>
    <div class="card"><h3>Ryan's Circle picks</h3><p><b>Columbia</b> for the 1905 salad and sangria · <b>Venezia</b> for pizza and the best people-watching patio · <b>Blu Kouzina</b> for grilled octopus and meze · <b>Green Zebra</b> for breakfast or a smoothie before the beach.</p></div>
  </div>
  <div class="two">
    <div class="card"><h3>Getting around</h3><p><b>Lido Beach</b> is a 5-minute walk up John Ringling Blvd; turn right on Ben Franklin for quieter <b>North Lido</b>.<br><b>Bay Runner trolley</b> is free and links Lido Beach, the Circle and downtown (SarasotaBayRunner.com).<br><b>Parking:</b> 1,600+ city spaces: the Fillmore lot, the N. Adams garage and the streets off the Circle.</p></div>
    <div class="card"><h3>2026–27 season on the Circle</h3><p style="font-size:6.3pt;line-height:1.42"><b>Oct 31</b> Fright Night trick-or-treat, 6–8pm · <b>Nov 7</b> Ferraris on the Circle · <b>Nov 14–15</b> Art Festival &amp; Sidewalk Sale · <b>Dec 5</b> Holiday Night of Lights, 5:30pm · <b>Dec</b> Porsches in the Park · <b>Jan 30–31</b> Art Festival · <b>Jan</b> Century of Cars · <b>May</b> Corvettes on the Circle · <b>May 29–30</b> Fine Art Festival · <b>June</b> Craft Festival &amp; Sidewalk Sale<br><span style="color:#8E9AA3">2027 dates set by each sponsor; see VisitStArmands.org</span></p></div>
  </div>
  <div class="contact"><img src="assets/adamson-group-logo.png" alt=""><div><div class="nm2">Ryan Adamson, PA</div><div class="r">Adamson Group · Coldwell Banker Realty<br>423 St. Armands Circle, Sarasota, FL 34236 · AdamsonFL.com</div></div><div class="ph2">(941) 713-9234<small>call or text · AdamsonFL.com</small></div></div>
</div>"""

html = f"""<!doctype html><html><head><meta charset="utf-8"><title>St. Armands Circle handout</title>
<style>{FONT_CSS}
{CSS}</style></head><body>{front}{back}</body></html>"""
open(f"{OUT}/stac_handout.html", "w").write(html)

pw = f"""
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page()
        await pg.goto('file://{OUT}/stac_handout.html', wait_until='networkidle'); await pg.evaluate('document.fonts.ready'); await pg.wait_for_timeout(600)
        await pg.pdf(path='{OUT}/stac_handout_bleed.pdf', width='5.75in', height='8.75in', print_background=True, margin={{'top':'0','right':'0','bottom':'0','left':'0'}})
        await b.close()
asyncio.run(main())
"""
subprocess.run([sys.executable, "-c", pw], check=True, env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")})
# trim version: crop the bleed off
try:
    from pypdf import PdfReader, PdfWriter
    rd = PdfReader(f"{OUT}/stac_handout_bleed.pdf"); wr = PdfWriter()
    for pg in rd.pages:
        pg.mediabox.lower_left = (BLEED, BLEED); pg.mediabox.upper_right = (414 - BLEED, 630 - BLEED); wr.add_page(pg)
    wr.write(f"{OUT}/stac_handout_trim.pdf")
except Exception as e:
    print("trim pdf skipped:", e)
os.remove(f"{OUT}/_map.html")
print("wrote", OUT, "|", len(pins), "restaurants")
