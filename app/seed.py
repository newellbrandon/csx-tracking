"""One-shot seed: drop and reload the `csx_demo` database.

JSON/GeoJSON files in app/data/ are loader input only.
After this runs, MongoDB is the single source of truth.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import get_settings
from .db import close_client, get_db
from .geo import (
    cumulative_lengths_km,
    interpolate_along,
    linestring_coords,
    position_for,
    waypoint_progress,
)
from .indexes import ensure_events_timeseries, ensure_indexes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("csx.seed")

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load(name: str):
    with open(DATA_DIR / name) as fh:
        return json.load(fh)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def seed() -> None:
    settings = get_settings()
    db = get_db()

    log.info("Dropping database %s and reseeding", settings.CSX_DEMO_DB)
    client = db.client
    await client.drop_database(settings.CSX_DEMO_DB)

    customers = _load("customers.json")
    industries = _load("industries.json")
    yards = _load("yards.json")
    segments_fc = _load("network_segments.geojson")
    railcars = _load("railcars.json")
    trains = _load("trains.json")
    shipments = _load("shipments.json")

    if customers:
        await db.customers.insert_many(customers)
    if industries:
        await db.industries.insert_many(industries)
    if yards:
        await db.yards.insert_many(yards)
    if railcars:
        await db.railcars.insert_many(railcars)

    segment_docs = []
    for feat in segments_fc["features"]:
        props = feat["properties"]
        segment_docs.append({
            "segment_id": props["segment_id"],
            "name": props["name"],
            "endpoints": props["endpoints"],
            "waypoints": props["waypoints"],
            "geometry": feat["geometry"],
        })
    if segment_docs:
        await db.network_segments.insert_many(segment_docs)

    segments_by_id = {s["segment_id"]: s for s in segment_docs}

    train_docs = []
    for t in trains:
        seg = segments_by_id[t["route_segment_id"]]
        coords = linestring_coords(seg["geometry"])
        lng, lat = position_for(t["progress"], t["direction"], coords)
        train_docs.append({
            **t,
            "current_position": {"type": "Point", "coordinates": [lng, lat]},
            "updated_ts": _now(),
        })
    if train_docs:
        await db.trains.insert_many(train_docs)

    now = _now()
    shipment_docs = []
    for s in shipments:
        billed_offset = s.get("billed_at_origin_ts_offset_hours", -12)
        billed_ts = now + timedelta(hours=billed_offset)
        timeline = [{
            "ts": billed_ts,
            "type": "STATUS",
            "code": "BILLED_AT_ORIGIN",
            "description": f"Waybill released at {s['origin_industry']}",
            "location": s["origin_industry"],
        }]
        if s["status"] in {"in_transit", "at_yard", "delivered"}:
            timeline.append({
                "ts": billed_ts + timedelta(hours=2),
                "type": "STATUS",
                "code": "DEPARTED_ORIGIN",
                "description": f"Departed origin on train {s['current_train_symbol']}",
                "location": s["origin_industry"],
            })
        shipment_doc = {
            **{k: v for k, v in s.items() if k != "billed_at_origin_ts_offset_hours"},
            "billed_ts": billed_ts,
            "status_timeline": timeline,
            "updated_ts": now,
        }
        shipment_docs.append(shipment_doc)
    if shipment_docs:
        await db.shipments.insert_many(shipment_docs)

    await ensure_events_timeseries(db)
    await ensure_indexes(db)

    events: list[dict] = []
    train_by_symbol = {t["symbol"]: t for t in train_docs}
    waybill_to_train = {s["waybill_number"]: s["current_train_symbol"] for s in shipment_docs}
    for s in shipment_docs:
        sym = s["current_train_symbol"]
        eq_id = s["current_equipment_id"]
        t = train_by_symbol.get(sym)
        if not t:
            continue
        seg = segments_by_id[t["route_segment_id"]]
        coords = linestring_coords(seg["geometry"])
        for i in range(6):
            past_progress = max(0.0, t["progress"] - (5 - i) * 0.015)
            lng, lat = position_for(past_progress, t["direction"], coords)
            ts = now - timedelta(minutes=(5 - i) * 8)
            events.append({
                "ts": ts,
                "type": "GPS",
                "equipment_id": eq_id,
                "train_symbol": sym,
                "location": {"type": "Point", "coordinates": [lng, lat]},
                "raw": {"source": "seed_history", "progress": past_progress},
            })

        wp_coords_progress = [
            (wp["yard_code"], waypoint_progress(coords, idx))
            for idx, wp in enumerate(seg["waypoints"])
        ]
        for yard_code, wp_p in wp_coords_progress:
            if not yard_code:
                continue
            if t["direction"] == "reverse":
                effective = 1.0 - wp_p
            else:
                effective = wp_p
            if effective > t["progress"]:
                continue
            wp_lng, wp_lat = interpolate_along(coords, wp_p)
            arr_ts = now - timedelta(hours=(t["progress"] - effective) * 12 + 1)
            dep_ts = arr_ts + timedelta(minutes=35 + int(40 * (1 - effective)))
            events.append({
                "ts": arr_ts,
                "type": "AEI",
                "equipment_id": eq_id,
                "train_symbol": sym,
                "location": {"type": "Point", "coordinates": [wp_lng, wp_lat]},
                "raw": {"yard_code": yard_code, "direction": "arrival"},
            })
            events.append({
                "ts": dep_ts,
                "type": "AEI",
                "equipment_id": eq_id,
                "train_symbol": sym,
                "location": {"type": "Point", "coordinates": [wp_lng, wp_lat]},
                "raw": {"yard_code": yard_code, "direction": "departure"},
            })

    if events:
        events.sort(key=lambda e: e["ts"])
        await db.events.insert_many(events)
        log.info("Inserted %d starter events", len(events))

    log.info("Seed complete. db=%s collections=%s",
             settings.CSX_DEMO_DB, sorted(await db.list_collection_names()))


_reseed_lock = asyncio.Lock()


async def reseed() -> dict[str, int | str]:
    """Drop and reload csx_demo while the app is running (demo reset)."""
    async with _reseed_lock:
        settings = get_settings()
        db = get_db()
        log.info("Demo reset: dropping database %s and reseeding", settings.CSX_DEMO_DB)
        await seed()
        counts = {
            c: await db[c].count_documents({})
            for c in ["yards", "trains", "shipments", "events"]
        }
        log.info("Demo reset complete: %s", counts)
        return {"status": "ok", "database": settings.CSX_DEMO_DB, "counts": counts}


async def _main():
    try:
        await seed()
    finally:
        close_client()


if __name__ == "__main__":
    asyncio.run(_main())
