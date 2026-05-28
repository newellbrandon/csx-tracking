# CSX Tracking Demo

A FastAPI + MongoDB demo built for CSX

1. **`/track`** — paste a waybill (e.g. `WB-100023`) or equipment ID (e.g.
   `CSXT600105`) and watch the railcar's train move along its corridor on a
   Leaflet map, with a live status timeline streamed from a time-series
   collection.
2. **`/ops`** — run `$geoNear` queries against `trains.current_position` to
   answer "what hazmat tank cars are within N miles of yard X?", or list all
   cars currently parked at a yard.
3. **`/pulse`** — analytics dashboard backed entirely by aggregation pipelines:
   KPI tiles, cars-per-yard bar, top commodities in motion, dwell-time
   leaders (from the events time-series), and per-train velocity.

The point of the demo: MongoDB's data platform — schema, 2dsphere geospatial
indexes, time-series collections, and the aggregation framework — handles a
realistic rail-ops workload end-to-end. 

## Data-handling contract

MongoDB is the only state at runtime.

- JSON / GeoJSON in [app/data/](app/data/) is loader input only, consumed by
  [app/seed.py](app/seed.py). After seed, the running app never reads those
  files.
- The background sim reads train and segment state from MongoDB every tick
  and writes the advanced state back — it holds no in-process cache.

## Requirements

- Python 3.11+ (3.13 tested)
- MongoDB Atlas CLI (`atlas`) — [install docs](https://www.mongodb.com/docs/atlas/cli/stable/install-atlas-cli/)
- Atlas Local on `localhost:27017` (via Atlas CLI, or Docker as a fallback)

If you don't already have Atlas Local running:

**Recommended — Atlas CLI**

```bash
atlas local setup mongodb-atlas --port 27017 --username dbuser --password donotpass --connectWith connectionString --force
```

Use the matching URI in `.env` (see Environment below).

**Alternative — Docker**

```bash
docker run -d --name csx-mongo \
  -p 27017:27017 \
  -e MONGODB_INITDB_ROOT_USERNAME=dbuser \
  -e MONGODB_INITDB_ROOT_PASSWORD=donotpass \
  mongodb/mongodb-atlas-local:latest
```

## Environment

Only `MONGODB_URI` is required. Defaults are baked in for everything else;
see [.env.example](.env.example). This matches the Atlas CLI setup above
(and the Docker fallback).

```
MONGODB_URI=mongodb://dbuser:donotpass@localhost:27017/?authSource=admin&directConnection=true
# CSX_DEMO_DB=csx_demo
# API_HOST=0.0.0.0
# API_PORT=8088
# SIM_INTERVAL_SECONDS=5.0
# SIM_STEP_KM=18.0
```

The demo writes into a dedicated `csx_demo` database (override with
`CSX_DEMO_DB`) so any pre-existing databases on the same cluster are
untouched.

## Run

```bash
./scripts/bootstrap.sh
```

That creates a venv if needed, installs deps, runs `app.seed` (drops and
reloads `csx_demo`, creates the `events` time-series collection, builds all
indexes), and starts uvicorn at `http://localhost:8088`.

Manual equivalent:

```bash
python3 -m venv venv
./venv/bin/pip install -e .
./venv/bin/python -m app.seed
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8088 --reload
```

## Demo script for the CSX AI team

1. Open `/track`, paste `WB-100023`. Map zooms to the railcar; gold pulse
   marker shows the train (M408) moving along the Chicago–Florida corridor.
   The timeline panel updates every 5 s as the sim emits new `GPS` events
   into the `events` time-series.
2. Switch to `/ops`. Pick `WCS` (Waycross), set 200 mi, commodity-class
   `chemical`, hazmat = "Hazmat only", and submit. A gold radius ring and
   navy car markers are drawn from a `$geoNear` pipeline that lookups
   shipments and railcars.
3. Click "Or: cars at selected yard" with `HMT` (Hamlet) selected — yard
   inventory query against the `at_yard` shipments.
4. Switch to `/pulse`. KPI tiles update every 15 s. Cars-per-yard bar
   (`$match` + `$group` + `$lookup`). Dwell-time leaders are computed from
   the `events` time-series via `$reduce` pairing arrival/departure AEI
   events per `(equipment_id, yard_code)`. Train velocity uses successive
   GPS points within a 2-hour window and great-circle math.
5. In Atlas Local (Compass, mongosh, or the MongoDB MCP server), show the
   schema, the 2dsphere indexes on `trains.current_position` and
   `events.location`, and the `events` time-series collection metadata
   (`metaField=equipment_id`, `granularity=seconds`). Or hit `GET /api/indexes`
   for a JSON summary of all indexes.
6. On each page, expand **Underlying MQL** panels to show the exact mongosh
   queries with syntax highlighting — copy them straight into a shell demo.

## Exposing underlying MQL

Every JSON API response includes an `mql` object with the exact operations
executed against MongoDB:

```json
{
  "mql": {
    "database": "csx_demo",
    "operations": [{ "collection": "shipments", "operation": "find", "filter": { ... } }],
    "shell": "db.getSiblingDB('csx_demo').shipments.find(...)"
  }
}
```

In the UI:

- **Track** — expandable "Underlying MQL — shipment trace" panel (all `find()` calls).
- **Timeline & Ops results** — MQL embed on every HTMX refresh.
- **Pulse** — five expandable panels at the bottom, one per aggregation pipeline.
- **Copy MQL** — copies the highlighted mongosh snippet to the clipboard.

Syntax highlighting: highlight.js (Atom One Dark). Additional endpoint:
`GET /api/indexes` lists all collection indexes for walkthroughs.

## Architecture

```
Browser
   |  HTMX poll, Leaflet, Chart.js
FastAPI (Jinja2)
   |  Motor (MONGODB_URI)
MongoDB
  - customers, industries, yards, network_segments (2dsphere)
  - railcars, trains (2dsphere), shipments
  - events  (time-series; metaField=equipment_id)
Background sim task --> writes trains.current_position + events
```

### Collections

| Collection         | Purpose                                                    | Notable indexes                          |
|--------------------|------------------------------------------------------------|------------------------------------------|
| `customers`        | Shippers / consignees                                      | unique `code`, 2dsphere `hq`             |
| `industries`       | Customer plant sites                                       | unique `code`, 2dsphere `location`       |
| `yards`            | CSX yards                                                  | unique `code`, 2dsphere `location`       |
| `network_segments` | GeoJSON LineStrings for major corridors                    | unique `segment_id`, 2dsphere `geometry` |
| `railcars`         | Equipment master                                           | unique `equipment_id`                    |
| `trains`           | Train symbols with current position + route                | unique `symbol`, 2dsphere `current_position` |
| `shipments`        | Waybills, status, timeline                                 | unique `waybill_number`, `status+commodity_class` |
| `events`           | Time-series of `GPS` / `AEI` / `STATUS` events             | `equipment_id+ts` (auto), `train_symbol+ts`, 2dsphere `location` |

### Notable pipelines

- **`/api/cars/near`** — `$geoNear` on `trains.current_position` →
  `$lookup` shipments → `$lookup` railcars → `$match` filters → `$project`.
- **`/api/pulse/kpi`** — single `$facet` over `shipments` for transit
  counts + a follow-up `$group` over `events` for velocity.
- **`/api/pulse/dwell_leaders`** — `$reduce` over per-`(equipment_id,
  yard_code)` AEI event arrays to pair arrival/departure timestamps.
- **`/api/pulse/train_velocity`** — `$group` GPS events per train within a
  rolling 2-hour window; great-circle distance computed in Python from
  the grouped point arrays.

## Where Atlas Stream Processing would plug in

The in-app sim is a placeholder for real telemetry. To swap to a real
stream:

1. Replace the asyncio task in [app/sim.py](app/sim.py) with a producer
   publishing AEI scanner reads and GPS pings to a Kafka topic
   (`csx.events.raw`).
2. Define an Atlas Stream Processor:
   - `$source` — Kafka `csx.events.raw`
   - `$tumblingWindow` per `equipment_id`, 30 s — collapse duplicate AEI
     reads, take latest GPS per window
   - `$merge` into `csx_demo.events` (the same time-series collection the
     UI already reads)
   - `$emit` to `csx.alerts.dwell` whenever a window's dwell exceeds
     `p95 * 1.5` for that yard.
3. UI and aggregation APIs are unchanged — they always read from
   `csx_demo.events`.

## File layout

```
app/
  main.py              FastAPI app + lifespan
  config.py            pydantic-settings reading .env
  db.py                single shared Motor client
  geo.py               stateless geometry helpers
  mql.py               format mongosh-style MQL for API responses
  jinja_env.py         shared Jinja2 env (tojson filter)
  indexes.py           all index creation
  seed.py              one-shot loader (drops + reloads csx_demo)
  sim.py               background train sim
  routes/
    pages.py           /, /track, /ops, /pulse
    api.py             /api/shipment, /api/positions, /api/timeline,
                       /api/cars/near, /api/cars/at_yard, /api/yards,
                       /api/network, /api/pulse/*, /api/indexes
  data/                JSON + GeoJSON loader input
templates/             Jinja2 with CSX-styled chrome + _mql_embed.html
static/css/app.css     CSX palette CSS custom properties + Inter
static/js/             track.js, ops.js, pulse.js, mql.js
scripts/bootstrap.sh   install deps, seed, run
```
