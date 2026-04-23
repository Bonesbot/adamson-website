# Polygon GeoJSON files

Source-of-truth GeoJSON files for area and sub-zone boundaries. Draw in
<https://geojson.io>, save here, then load with:

```
python supabase/load_polygon.py supabase/polygons/<filename>.geojson \
    --area-slug <slug> --zone-name "<name>" --reenrich
```

See `../POLYGON_WORKFLOW.md` for the full workflow.

## Naming convention

- `<area-slug>.geojson` — a polygon for the whole area
  (e.g. `bird-key.geojson`, `st-armands.geojson`)
- `<area-slug>__<sub-zone>.geojson` — a sub-zone within an area
  (e.g. `longboat-key__north-end.geojson`, `longboat-key__gulf-front.geojson`)

Keeping files git-tracked means polygon revisions show up in history —
if a boundary decision needs to be reconsidered later, the diff tells
the story.
