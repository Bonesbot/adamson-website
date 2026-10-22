"""Geocode the St. Armands restaurant list via OSM Nominatim (ODbL; OSM is already the
map's attributed tile source). Tries the business name first (hits the OSM POI node when
one exists), falls back to the street address, and sanity-checks every hit against a
tight bounding box around the Circle. Writes stac_geocoded.json next to the input."""
import json, sys, time, urllib.parse, urllib.request

HERE = sys.argv[1] if len(sys.argv) > 1 else "scripts/srqmap"
src = json.load(open(f"{HERE}/stac_restaurants.json"))
UA = {"User-Agent": "srqmap-geocoder/1.0 (adamsonfl.com; ryan@adamsonfl.com)"}
BOX = (27.3135, 27.3205, -82.5820, -82.5720)  # lat_min, lat_max, lng_min, lng_max


def nom(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"format": "json", "limit": 3, "q": q, "countrycodes": "us"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def inbox(h):
    la, lo = float(h["lat"]), float(h["lon"])
    return BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]


out = []
for p in src:
    hit, how = None, None
    for how_, q in (("name", p["q"] + " Sarasota FL"), ("address", p["address"])):
        try:
            res = [h for h in nom(q) if inbox(h)]
        except Exception as e:
            res = []
            print("ERR", p["key"], e)
        time.sleep(1.1)
        if res:
            hit, how = res[0], how_
            break
    rec = dict(p)
    if hit:
        rec["lat"] = round(float(hit["lat"]), 6)
        rec["lng"] = round(float(hit["lon"]), 6)
        rec["geocode"] = {"how": how, "osm": f'{hit["osm_type"]}/{hit["osm_id"]}', "display": hit["display_name"][:80]}
    else:
        rec["lat"] = rec["lng"] = None
        rec["geocode"] = {"how": "none"}
    print(f'{p["key"]:28s} {how or "MISS":8s} {rec["lat"]} {rec["lng"]}  {rec["geocode"].get("display","")}')
    out.append(rec)

json.dump(out, open(f"{HERE}/stac_geocoded.json", "w"), indent=1)
