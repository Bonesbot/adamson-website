"""Merge the geocoded St. Armands Circle restaurant list into src/data/srqmap-pins.json.

- Adds each as group "dining" with tier "minor" + place "stac" so the map can render them
  subtly (SRQmap.astro hides minor pins at the default zoom and reveals them as you zoom
  into the Circle). Existing full pins on the Circle (Columbia, Cafe on St Armands,
  Venezia, Green Zebra) are left as-is but tagged place "stac" so they count in the hub.
- Idempotent: pins are keyed by id "stac-<key>"; re-running updates in place.
"""
import json, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PINS = f"{ROOT}/src/data/srqmap-pins.json"
pins = json.load(open(PINS))
geo = json.load(open(f"{ROOT}/scripts/srqmap/stac_geocoded.json"))

# Hand corrections where Nominatim fell back to a road centreline instead of the storefront.
# Interpolated between geocoded neighbours on the same block (see geocode log).
FIX = {
    "cilantro-grill": (27.319160, -82.577030),   # 419A, between Cha Cha (417) and Cafe on St Armands (431)
    "blu-kouzina":    (27.319350, -82.578180),   # 25 N Blvd, between Lynches (19) and Ephesus (27)
    "starbucks-stac": (27.319330, -82.576400),   # 443E, between Cafe on St Armands (431) and Tommy Bahama (465)
    "i-love-candy":   (27.318450, -82.576150),   # 440 JRB, between Crab & Fin (420) and Blue Dolphin (470)
}
WEB = {
    "15-south-napule": "https://www.15south-bynapule.com/",
    "tommy-bahama-restaurant": "https://www.tommybahama.com/restaurants-and-marlin-bars",
    "blu-kouzina": "https://blukouzina.com/",
    "lynches-pub": "https://lynches.pub/",
    "blue-dolphin-cafe": "https://www.bluedolphincafe.com/",
}

by_id = {p.get("id"): p for p in pins}
added = updated = 0
for r in geo:
    lat, lng = FIX.get(r["key"], (r["lat"], r["lng"]))
    if lat is None:
        print("SKIP (no coords):", r["key"]); continue
    pin = {
        "id": f'stac-{r["key"]}',
        "group": "dining",
        "tier": "minor",
        "place": "stac",
        "name": r["name"],
        "lat": lat, "lng": lng,
        "address": r["address"],
        "blurb": r["blurb"],
        "tip": r["tip"],
        "price": r["price"], "vibe": r["vibe"], "good_for": r["good_for"], "food_style": r["food_style"],
        "website": WEB.get(r["key"], r["website"]),
        "quadrant": r["quadrant"],
    }
    if r.get("phone"): pin["phone"] = r["phone"]
    pin = {k: v for k, v in pin.items() if v not in ("", None)}
    if pin["id"] in by_id:
        by_id[pin["id"]].clear(); by_id[pin["id"]].update(pin); updated += 1
    else:
        pins.append(pin); by_id[pin["id"]] = pin; added += 1

# Tag the four existing full-size Circle dining pins so the hub count includes them.
EXISTING = {"Cafe on St Armands": "Gold", "Columbia Restaurant": "Gold", "Venezia Italian Restaurant": "Pink", "Green Zebra (St Armands)": "Aqua"}
for p in pins:
    if p.get("group") == "dining" and p["name"] in EXISTING:
        p["place"] = "stac"; p.setdefault("quadrant", EXISTING[p["name"]])

json.dump(pins, open(PINS, "w"), indent=2, ensure_ascii=False)
print(f"added {added}, updated {updated}, total pins {len(pins)}, stac dining {sum(1 for p in pins if p.get('place')=='stac')}")
