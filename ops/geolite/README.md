# GeoLite2 Operator Guide

This directory holds the optional MaxMind GeoLite2-City database used by IntelliBird for
IP-to-geo resolution (requirement MAP-05). The `.mmdb` binary is **never committed** to the
repository. Only this README and `.gitkeep` are tracked.

## Purpose

When present, the GeoLite2-City database enables IntelliBird workers to resolve source IP
addresses from ingested events into latitude/longitude coordinates for display on the threat
map. When the file is absent workers skip IP resolution silently — events that carry STIX
`location` objects still resolve coordinates via their embedded data.

## Download

Four options — pick one:

### Option A (Recommended): Compose `geoip` profile sidecar

`docker-compose.yml` ships a `geoip-update` service (profile `geoip`) that
downloads City + ASN + Country `.mmdb` from wp-statistics via jsDelivr and
stores them in the shared named volume `geoip`. Worker + scheduler mount it
read-only.

Run on demand:

```bash
docker compose --profile geoip run --rm geoip-update
# Then restart workers to pick up the new mmdb:
docker compose restart worker scheduler
```

Schedule it via cron on the host for weekly refresh:

```
0 3 * * 1  cd /path/to/IntelliBird/ops && docker compose --profile geoip run --rm geoip-update
```

### Option B: P3TERX mirror (host bind mount)

Pre-packaged `.mmdb` files, updated weekly, no registration:

- <https://github.com/P3TERX/GeoLite.mmdb>

```bash
curl -L -o ops/geolite/GeoLite2-City.mmdb \
  https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb
```

Switch the compose worker volume from `geoip:` to `./geolite:/app/geolite:ro`
(commented example in docker-compose.yml).

### Option C: wp-statistics mirror (direct, no Docker)

- <https://github.com/wp-statistics/GeoLite2-City>

```bash
curl -L -o ops/geolite/GeoLite2-City.mmdb \
  https://raw.githubusercontent.com/wp-statistics/GeoLite2-City/master/GeoLite2-City.mmdb
```

### Option D: Official MaxMind (free registration required)

1. Register for a free MaxMind account at <https://dev.maxmind.com/geoip/geolite2-free-geolocation-data>.
2. Navigate to **Download Files** → **GeoLite2-City** (`.mmdb` format).
3. Extract the archive and rename to exactly:

   ```
   GeoLite2-City.mmdb
   ```

## Install

Place the file in this directory so the path on the host is:

```
ops/geolite/GeoLite2-City.mmdb
```

Then add a `volumes:` entry to the `worker` service block in `ops/docker-compose.yml`:

```yaml
services:
  worker:
    volumes:
      - ./geolite:/app/geolite:ro
```

The backend reads the file path from the environment variable:

```
GEOLITE_PATH=/app/geolite/GeoLite2-City.mmdb
```

This is the default value — no override is needed unless you store the file elsewhere.

## Licence

The GeoLite2-City database is distributed by MaxMind under the
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/)
licence. You must attribute MaxMind and share any derivative databases under the same terms.
Refer to the MaxMind GeoLite2 End User License Agreement for full terms.

The `.mmdb` binary **must not** be committed to version control.
