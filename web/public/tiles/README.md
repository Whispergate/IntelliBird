# pmtiles tileset

Phase 5 GeoMap (`web/app/components/GeoMap.tsx`) reads `world.pmtiles` from this directory unless `NEXT_PUBLIC_MAP_TILES_URL` overrides the path.

Expected: small Protomaps world (zoom 0-6, ~10MB, MIT).

Download: `curl -L https://build.protomaps.com/20240101.pmtiles -o world.pmtiles`

Operator override: set `NEXT_PUBLIC_MAP_TILES_URL=https://your-cdn/world.pmtiles` to bypass the baked-in asset entirely.

This file is intentionally large and checked into the web image at build time; operators running dev outside the container can replace it at any time.
