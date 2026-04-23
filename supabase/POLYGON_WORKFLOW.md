# PostGIS Zone Polygons — Draw → Load → Segment

How to draw a submarket boundary on a map, load it into Supabase, and have
every listing automatically bucketed into the right area.

---

## Why this exists

The MLS `PostalCode` field is a poor area classifier in Sarasota:

| Zip   | Areas it covers                                        |
|-------|--------------------------------------------------------|
| 34228 | Longboat Key (clean — 1:1)                             |
| 34242 | Siesta Key (clean — 1:1)                               |
| 34236 | Downtown Sarasota **and** Lido Key **and** St. Armands **and** Bird Key |

Four of our six submarkets share one zip. Without polygons every listing
in 34236 collapses into whichever area the trigger finds first in the
`areas` table (currently Downtown Sarasota).

Polygons solve this by doing containment lookups (`ST_Within`) on the
listing's lat/long, falling back to the zip rule only when a listing has
no coordinates or lands outside every drawn polygon.

---

## One-time setup

Run the SQL scripts in order against the Supabase database (SQL Editor or
psql, see `SETUP.md`):

1. `01_tables.sql`       — schema (already deployed)
2. `02_trigger.sql`      — original enrichment trigger (already deployed)
3. `03_views_seeds_grants.sql` — views + areas seed (already deployed)
4. **`04_polygon_area_detection.sql`** — polygon-first detection + re-enrich helper

Step 4 is the new piece. It replaces `fn_compute_enrichments()` with a
version that does `ST_Within()` first and zip fallback second, and adds
two helpers:

- `fn_reenrich_all_listings()` — re-runs enrichment on every row so
  existing listings pick up newly-loaded polygons.
- `vw_area_listing_counts` — quick visibility into how listings are
  bucketed by `detected_area`.

---

## Drawing a polygon in geojson.io

1. Open <https://geojson.io>
2. Pan/zoom to the area (e.g. Bird Key is just east of St. Armands Circle)
3. Click the **polygon tool** in the right toolbar (the shape with dots)
4. Click around the shoreline / boundary to place vertices; double-click
   the first vertex to close the polygon
5. With the polygon selected, click **Info** (or the shape in the sidebar)
   and add properties via the `+` button:
   - `area_slug` → must match a row in the `areas` table
     (`longboat-key`, `downtown-sarasota`, `lido-key`, `siesta-key`,
     `st-armands`, `bird-key`)
   - `zone_name` → human label, e.g. `"Bird Key"` or
     `"Longboat Key — North End"`. Used as the idempotency key
     with `area_slug` — re-running the loader with the same pair
     **replaces** the polygon, so you can refine and re-load freely.
   - `zone_type` → optional tag like `island`, `beachfront`, `bayside`,
     `golf_course`, `downtown`. Used later for granular AEO
     segmentation views.
6. **Save → Save as GeoJSON** (top-left menu). Put the file somewhere
   under the repo, e.g. `supabase/polygons/bird-key.geojson`.

### Tip: you can skip the property editor

If fiddling with the geojson.io property UI is annoying, just save the
file with no properties and pass everything on the command line:

```
python supabase/load_polygon.py supabase/polygons/bird-key.geojson \
    --area-slug bird-key \
    --zone-name "Bird Key" \
    --zone-type island \
    --reenrich
```

### Tip: one file with many polygons

For a pass through all 6 areas at once, draw them all in a single
geojson.io session, set properties per-polygon in the editor, save one
GeoJSON file, and run the loader once with no CLI flags.

---

## Loading a polygon

From the repo root:

```
# Single file, properties via CLI, re-enrich existing listings
python supabase/load_polygon.py supabase/polygons/bird-key.geojson \
    --area-slug bird-key \
    --zone-name "Bird Key" \
    --zone-type island \
    --reenrich

# Dry run first if you want to preview
python supabase/load_polygon.py supabase/polygons/bird-key.geojson \
    --area-slug bird-key \
    --zone-name "Bird Key" \
    --dry-run
```

The loader logs each polygon it processes and, with `--reenrich`, prints
the full area breakdown at the end so you can immediately see whether
the segmentation landed.

### Idempotency

Re-running with the same `(area_slug, zone_name)` pair deletes the
existing polygon and inserts the new one. So the refine loop is:

1. Draw v1 in geojson.io → save → load → re-enrich → check counts
2. Tweak boundary in geojson.io → save over same file → load again → re-enrich
3. Repeat until the area looks right

---

## Verifying a load

Quick SQL checks against the live database:

```sql
-- Count of listings per detected_area
SELECT * FROM vw_area_listing_counts;

-- Spot-check: what addresses are now tagged as bird-key?
SELECT unparsed_address, subdivision_name, current_price, mls_status
FROM raw_listings
WHERE detected_area = 'bird-key'
ORDER BY current_price DESC
LIMIT 20;

-- Did anything drop out of downtown-sarasota?
SELECT COUNT(*) FROM raw_listings WHERE detected_area = 'downtown-sarasota';

-- What's still bucketed as unassigned (no polygon + no zip match)?
SELECT COUNT(*) FROM raw_listings WHERE detected_area IS NULL;

-- Zone-level stats (joins raw_listings against zone_polygons directly)
SELECT * FROM vw_market_stats_by_zone;
```

---

## Sub-zones within an area

The schema allows multiple polygons per `area_slug`. Useful for:

- `longboat-key` / `Longboat Key — North End` (type: `neighborhood`)
- `longboat-key` / `Longboat Key — Gulf-front` (type: `beachfront`)
- `longboat-key` / `Longboat Key — Bayside` (type: `bayside`)

All three polygons can share `area_slug = 'longboat-key'` — they'll all
resolve `detected_area` to `longboat-key`, but `vw_market_stats_by_zone`
will keep them separate so you can write AEO content like "median price
for Gulf-front condos on Longboat Key" with real numbers.

When polygons overlap, the trigger picks the **smallest** polygon
(finest-grained zone) as the winner for `detected_area`.

---

## Files

| File | Purpose |
|------|---------|
| `supabase/04_polygon_area_detection.sql` | Updated trigger + re-enrich helper + area-count view |
| `supabase/load_polygon.py` | GeoJSON → Supabase loader (idempotent) |
| `supabase/polygons/` | Where to store `.geojson` source files (git-tracked) |
| `logs/polygons.log` | Loader output log |
