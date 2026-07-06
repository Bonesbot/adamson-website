#!/usr/bin/env python3
"""
Feature-listing scaffolder — creates/updates src/data/listings/<slug>.json and
pushes it to origin/main via the GitHub Contents API (Netlify rebuilds → page live).

The landing page template lives at src/pages/listings/[slug].astro; every field
in the JSON maps 1:1 to a section on the page. See LISTINGS_PLAYBOOK.md.

Modes
─────
1. Blank scaffold (off-market / pre-MLS — fill fields by hand, or let Claude do it):
     python scripts/listings/new_listing.py --slug 123-ocean-dr --address "123 Ocean Dr" \
       --city Sarasota --zip 34236 --neighborhood "Lido Shores" --price 4500000
2. MLS hydrate (listing already live in MLS → pulls key stats from Supabase):
     python scripts/listings/new_listing.py --slug 123-ocean-dr --mls A4650001
   Pulls current_price, beds, full/half baths, heated sqft, garage spaces, year built,
   lat/lng and public remarks from raw_listings (daily mls-export pipeline data).
3. Push an edited file:
     python scripts/listings/new_listing.py --slug 123-ocean-dr --push-only

Flags: --local (write file only, don't push) · --push-only (push existing file)
Requires repo .env (GITHUB_TOKEN; DATABASE_URL only needed for --mls).
NEVER hand-edit through the Cowork sandbox working tree (FUSE corruption) —
run this from Windows, or let it push via the Contents API.
"""
import argparse, base64, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV  = os.path.join(ROOT, '.env')

def load_env(path):
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

def gh(url, token, data=None, method='GET'):
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'new-listing/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def blank(a):
    return {
        "slug": a.slug, "status": a.status, "noindex": a.status == 'off-market',
        "tagline": a.tagline or "TAGLINE — e.g. One-Acre Privacy",
        "address": a.address or "STREET ADDRESS",
        "city": a.city or "Sarasota", "state": "FL", "zip": a.zip or "",
        "neighborhood": a.neighborhood or "",
        "price": a.price or 0,
        "open_house": "",
        "mls_id": a.mls or "",
        "beds": 0, "baths": 0, "sqft": 0, "garage": 0, "year_built": 0, "lot": "",
        "stats": [],
        "description": "1-2 sentence AEO summary: what/where/why it matters. Baked into meta + schema.",
        "features": [{"title": "Feature title", "text": "2-3 sentence description."} for _ in range(6)],
        "hero_image": "", "virtual_tour": "", "video_tour": "", "floor_plan": "",
        "map_query": "", "lat": 0, "lng": 0,
        "photos": [],
        "faq": [],
    }

def hydrate_from_mls(doc, mls_id):
    import psycopg2  # only needed for --mls
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute("""
        select unparsed_address, city, postal_code, subdivision_name, canonical_subdivision,
               current_price, bedrooms_total, bathrooms_full, bathrooms_half,
               living_area, garage_spaces, year_built, lot_size_acres,
               latitude, longitude
        from raw_listings where listing_id = %s limit 1""", (mls_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        sys.exit('MLS id %s not found in raw_listings (has the daily export run since it listed?)' % mls_id)
    (addr, city, zipc, subdiv, canon, price, beds, bfull, bhalf,
     sqft, garage, yb, acres, lat, lng) = row
    baths = (bfull or 0) + 0.5 * (bhalf or 0)
    baths = int(baths) if baths == int(baths) else baths
    doc.update({
        'address': (addr or doc['address']).split(',')[0].strip(),
        'city': city or doc['city'], 'zip': zipc or doc['zip'],
        'neighborhood': canon or subdiv or doc['neighborhood'],
        'price': int(price or 0), 'beds': int(beds or 0), 'baths': baths,
        'sqft': int(sqft or 0), 'garage': int(garage or 0), 'year_built': int(yb or 0),
        'lot': ('%s acres' % acres) if acres else '',
        'lat': float(lat or 0), 'lng': float(lng or 0),
        'mls_id': mls_id,
    })
    doc['stats'] = [
        {"value": '{:,}'.format(doc['sqft']), "label": "Heated Sq Ft"},
        {"value": str(doc['beds']), "label": "Bedrooms"},
        {"value": str(doc['baths']), "label": "Bathrooms"},
        {"value": str(doc['garage']), "label": "Car Garage"},
    ]
    doc['map_query'] = '%s, %s, FL %s' % (doc['address'], doc['city'], doc['zip'])
    return doc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', required=True)
    ap.add_argument('--mls', default='')
    ap.add_argument('--address', default=''); ap.add_argument('--city', default='')
    ap.add_argument('--zip', default='');     ap.add_argument('--neighborhood', default='')
    ap.add_argument('--tagline', default=''); ap.add_argument('--price', type=int, default=0)
    ap.add_argument('--status', default='active',
                    choices=['active', 'coming-soon', 'off-market', 'pending', 'sold'])
    ap.add_argument('--local', action='store_true', help='write file only, no push')
    ap.add_argument('--push-only', action='store_true', help='push existing local file as-is')
    a = ap.parse_args()

    assert re.match(r'^[a-z0-9-]+$', a.slug), 'slug must be kebab-case'
    load_env(ENV)
    rel = 'src/data/listings/%s.json' % a.slug
    local_path = os.path.join(ROOT, rel.replace('/', os.sep))

    if a.push_only:
        doc = json.load(open(local_path, encoding='utf-8'))
    else:
        doc = blank(a)
        if a.mls:
            doc = hydrate_from_mls(doc, a.mls)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        json.dump(doc, open(local_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('wrote', local_path)

    # sanity
    for k in ('slug', 'address', 'price'):
        assert doc.get(k), 'missing required field: ' + k

    if a.local:
        print('(--local: not pushed — edit the file, then rerun with --push-only)')
        return

    token = os.environ.get('GITHUB_TOKEN') or sys.exit('GITHUB_TOKEN missing from .env')
    repo = os.environ.get('GITHUB_REPO', 'Bonesbot/adamson-website')
    api = 'https://api.github.com/repos/%s/contents/%s' % (repo, rel)
    sha = None
    try:
        sha = gh(api + '?ref=main', token)['sha']
    except Exception:
        pass
    body = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
    payload = {'message': 'listing: %s %s' % ('update' if sha else 'add', a.slug),
               'content': base64.b64encode(body.encode()).decode(), 'branch': 'main'}
    if sha:
        payload['sha'] = sha
    res = gh(api, token, data=json.dumps(payload).encode(), method='PUT')
    print('PUSHED', rel, res['commit']['sha'][:10])
    print('Live after Netlify build: https://adamsonfl.com/listings/' + a.slug)

if __name__ == '__main__':
    main()
