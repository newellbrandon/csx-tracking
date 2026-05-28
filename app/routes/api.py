"""API endpoints. Every read goes through MongoDB via the shared Motor client."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from ..db import get_db
from ..jinja_env import env
from ..mql import format_operations, mql_aggregate, mql_find

templates = Jinja2Templates(env=env)
log = logging.getLogger("csx.api")

router = APIRouter()


def _clean(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, list):
            out[k] = [_clean(x) if isinstance(x, dict) else (x.isoformat() if isinstance(x, datetime) else x) for x in v]
        elif isinstance(v, dict):
            out[k] = _clean(v)
        else:
            out[k] = v
    return out


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%b %d %H:%M UTC")


@router.post("/reset")
async def reset_demo():
    """Drop and reload csx_demo so trains, events, and timelines replay from the start."""
    from ..seed import reseed

    try:
        return await reseed()
    except Exception as exc:
        log.exception("demo reset failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/health")
async def health():
    db = get_db()
    await db.command("ping")
    return {
        "status": "ok",
        "database": db.name,
        "collections": sorted(await db.list_collection_names()),
    }


@router.get("/indexes")
async def list_indexes():
    """List all indexes — useful for demo walkthrough."""
    db = get_db()
    out: dict[str, list] = {}
    for name in sorted(await db.list_collection_names()):
        if name.startswith("system."):
            continue
        info = await db[name].index_information()
        out[name] = [
            {"name": idx_name, "key": spec["key"], "unique": spec.get("unique", False)}
            for idx_name, spec in info.items()
        ]
    return {"database": db.name, "indexes": out}


@router.get("/shipment/{ident}")
async def shipment_by_id(ident: str):
    """Look up a shipment by waybill_number OR equipment_id."""
    db = get_db()
    ident = ident.strip().upper()
    ship_filter = {
        "$or": [
            {"waybill_number": ident},
            {"current_equipment_id": ident},
        ]
    }
    ship = await db.shipments.find_one(ship_filter)
    if not ship:
        raise HTTPException(status_code=404, detail=f"No shipment for '{ident}'")

    mql_ops = [mql_find("shipments", ship_filter)]

    train_sym = ship.get("current_train_symbol")
    train = None
    if train_sym:
        train_filter = {"symbol": train_sym}
        train = await db.trains.find_one(train_filter)
        mql_ops.append(mql_find("trains", train_filter))

    segment = None
    yards_on_route: list[dict] = []
    if train:
        seg_filter = {"segment_id": train["route_segment_id"]}
        segment = await db.network_segments.find_one(seg_filter)
        mql_ops.append(mql_find("network_segments", seg_filter))
        if segment:
            yard_codes = [w["yard_code"] for w in segment.get("waypoints", []) if w.get("yard_code")]
            if yard_codes:
                yards_filter = {"code": {"$in": yard_codes}}
                yards_on_route = await db.yards.find(yards_filter).to_list(length=None)
                mql_ops.append(mql_find("yards", yards_filter))

    eq_id = ship["current_equipment_id"]
    events_filter = {"equipment_id": eq_id}
    events_cursor = db.events.find(events_filter).sort("ts", -1).limit(40)
    events = await events_cursor.to_list(length=None)
    mql_ops.append(mql_find("events", events_filter, sort=[("ts", -1)], limit=40))

    return {
        "shipment": _clean(ship),
        "train": _clean(train),
        "segment": _clean(segment),
        "yards": [_clean(y) for y in yards_on_route],
        "events": [_clean(e) for e in events],
        "mql": format_operations(mql_ops),
    }


@router.get("/positions")
async def positions(train_symbol: str = Query(...)):
    db = get_db()
    filt = {"symbol": train_symbol}
    proj = {"symbol": 1, "current_position": 1, "status": 1, "progress": 1, "updated_ts": 1, "description": 1}
    train = await db.trains.find_one(filt, proj)
    if not train:
        raise HTTPException(status_code=404, detail=f"No train {train_symbol}")
    doc = _clean(train)
    doc["mql"] = format_operations([mql_find("trains", filt, projection=proj)])
    return doc


@router.get("/timeline")
async def timeline_partial(request: Request, waybill: str = Query(...)):
    db = get_db()
    ship = await db.shipments.find_one({"waybill_number": waybill})
    if not ship:
        raise HTTPException(status_code=404, detail=f"No shipment {waybill}")
    eq_id = ship["current_equipment_id"]
    events_filter = {"equipment_id": eq_id}
    recent = await db.events.find(events_filter).sort("ts", -1).limit(25).to_list(length=None)
    mql_block = format_operations([mql_find("events", events_filter, sort=[("ts", -1)], limit=25)])
    items: list[dict] = []
    yards = await db.yards.find().to_list(length=None)
    yard_by_code = {y["code"]: y for y in yards}
    for ev in recent:
        ts = ev["ts"]
        ev_type = ev["type"]
        raw = ev.get("raw", {}) or {}
        if ev_type == "GPS":
            label = "GPS Ping"
            loc = "enroute"
            css = "gps"
        elif ev_type == "AEI":
            yard_code = raw.get("yard_code")
            direction = raw.get("direction", "scan")
            yard_name = yard_by_code.get(yard_code, {}).get("name", yard_code or "")
            label = f"AEI {direction.title()} at {yard_name}"
            loc = f"Yard {yard_code}" if yard_code else ""
            css = "aei"
        else:
            label = raw.get("description") or ev.get("code") or ev_type
            loc = raw.get("location", "")
            css = "status"
        items.append({"ts": _fmt_ts(ts), "label": label, "loc": loc, "css": css})

    for s_evt in reversed(ship.get("status_timeline", [])):
        ts = s_evt.get("ts")
        items.append({
            "ts": _fmt_ts(ts),
            "label": s_evt.get("description") or s_evt.get("code"),
            "loc": s_evt.get("location", ""),
            "css": "status",
        })

    return templates.TemplateResponse(request, "_timeline.html", {"items": items, "mql": mql_block})


# ---------- Ops endpoints (filled in tracking and ops todos) ----------

@router.get("/cars/near")
async def cars_near(
    request: Request,
    lng: float = Query(...),
    lat: float = Query(...),
    miles: float = Query(50.0, ge=1, le=500),
    hazmat: bool | None = Query(None),
    car_type: str | None = Query(None),
    commodity_class: str | None = Query(None),
):
    db = get_db()
    meters = miles * 1609.344
    pipeline: list[dict[str, Any]] = [
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [lng, lat]},
            "distanceField": "distance_m",
            "maxDistance": meters,
            "spherical": True,
            "key": "current_position",
        }},
    ]
    pipeline += [
        {"$lookup": {
            "from": "shipments",
            "localField": "symbol",
            "foreignField": "current_train_symbol",
            "as": "shipments",
        }},
        {"$unwind": "$shipments"},
        {"$lookup": {
            "from": "railcars",
            "localField": "shipments.current_equipment_id",
            "foreignField": "equipment_id",
            "as": "car",
        }},
        {"$unwind": "$car"},
    ]
    match: dict[str, Any] = {}
    if hazmat is not None:
        match["car.hazmat"] = hazmat
    if car_type:
        match["car.car_type"] = car_type
    if commodity_class:
        match["car.commodity_class"] = commodity_class
    if match:
        pipeline.append({"$match": match})

    pipeline += [
        {"$project": {
            "_id": 0,
            "train_symbol": "$symbol",
            "train_description": "$description",
            "current_position": "$current_position",
            "distance_miles": {"$divide": ["$distance_m", 1609.344]},
            "waybill_number": "$shipments.waybill_number",
            "equipment_id": "$car.equipment_id",
            "car_type": "$car.car_type",
            "commodity": "$shipments.commodity",
            "commodity_class": "$car.commodity_class",
            "hazmat": "$car.hazmat",
            "shipper": "$shipments.shipper.name",
            "consignee": "$shipments.consignee.name",
            "status": "$shipments.status",
        }},
        {"$sort": {"distance_miles": 1}},
        {"$limit": 200},
    ]
    rows = await db.trains.aggregate(pipeline).to_list(length=None)
    mql_block = format_operations([mql_aggregate("trains", pipeline)])

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "_car_results.html", {"rows": rows, "miles": miles, "mql": mql_block},
        )
    return {"count": len(rows), "rows": [_clean(r) for r in rows], "mql": mql_block}


@router.get("/cars/at_yard")
async def cars_at_yard(request: Request, yard_code: str = Query(...)):
    db = get_db()
    yard = await db.yards.find_one({"code": yard_code.upper()})
    if not yard:
        raise HTTPException(status_code=404, detail=f"No yard {yard_code}")

    pipeline = [
        {"$match": {
            "$or": [
                {"current_yard_code": yard["code"]},
                {"status": "at_yard", "current_yard_code": yard["code"]},
            ]
        }},
        {"$lookup": {
            "from": "railcars",
            "localField": "current_equipment_id",
            "foreignField": "equipment_id",
            "as": "car",
        }},
        {"$unwind": "$car"},
        {"$project": {
            "_id": 0,
            "waybill_number": 1,
            "equipment_id": "$current_equipment_id",
            "car_type": "$car.car_type",
            "commodity": 1,
            "hazmat": 1,
            "shipper": "$shipper.name",
            "consignee": "$consignee.name",
        }},
        {"$sort": {"waybill_number": 1}},
    ]
    rows = await db.shipments.aggregate(pipeline).to_list(length=None)
    mql_block = format_operations([mql_aggregate("shipments", pipeline)])
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "_car_results.html",
            {"rows": rows, "miles": None, "yard": _clean(yard), "mql": mql_block},
        )
    return {"yard": _clean(yard), "count": len(rows), "rows": [_clean(r) for r in rows], "mql": mql_block}


@router.get("/yards")
async def list_yards():
    db = get_db()
    filt: dict[str, Any] = {}
    yards = await db.yards.find(filt, {"_id": 0}).to_list(length=None)
    return {"yards": yards, "mql": format_operations([mql_find("yards", filt, projection={"_id": 0})])}


@router.get("/network")
async def network():
    """Full GeoJSON FeatureCollection of the rail network."""
    db = get_db()
    filt: dict[str, Any] = {}
    segs = await db.network_segments.find(filt, {"_id": 0}).to_list(length=None)
    features = [{
        "type": "Feature",
        "properties": {
            "segment_id": s["segment_id"],
            "name": s["name"],
        },
        "geometry": s["geometry"],
    } for s in segs]
    return {
        "type": "FeatureCollection",
        "features": features,
        "mql": format_operations([mql_find("network_segments", filt, projection={"_id": 0})]),
    }


# ---------- Pulse endpoints (filled in pulse-ui todo) ----------

@router.get("/pulse/kpi")
async def pulse_kpi():
    db = get_db()
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    facets = await db.shipments.aggregate([
        {"$facet": {
            "trains_in_motion": [
                {"$match": {"status": "in_transit"}},
                {"$group": {"_id": "$current_train_symbol"}},
                {"$count": "n"},
            ],
            "cars_in_motion": [
                {"$match": {"status": "in_transit"}},
                {"$count": "n"},
            ],
            "active_waybills": [
                {"$match": {"status": {"$in": ["in_transit", "at_yard"]}}},
                {"$count": "n"},
            ],
        }},
    ]).to_list(length=1)
    f = facets[0] if facets else {}

    velocity_pipeline = [
        {"$match": {"type": "GPS", "ts": {"$gte": one_hour_ago}}},
        {"$sort": {"train_symbol": 1, "ts": 1}},
        {"$group": {
            "_id": "$train_symbol",
            "coords": {"$push": "$location.coordinates"},
            "ts": {"$push": "$ts"},
            "n": {"$sum": 1},
        }},
        {"$match": {"n": {"$gte": 2}}},
    ]
    velocity_rows = await db.events.aggregate(velocity_pipeline).to_list(length=None)

    from ..geo import haversine_km
    speeds = []
    for r in velocity_rows:
        coords = r["coords"]
        tss = r["ts"]
        dist_km = 0.0
        for i in range(1, len(coords)):
            dist_km += haversine_km(tuple(coords[i - 1]), tuple(coords[i]))
        hours = (tss[-1] - tss[0]).total_seconds() / 3600.0
        if hours > 0:
            speeds.append(dist_km / hours)
    avg_kmh = round(sum(speeds) / len(speeds), 1) if speeds else 0.0

    def _n(name: str) -> int:
        rows = f.get(name) or []
        return rows[0]["n"] if rows else 0

    return {
        "trains_in_motion": _n("trains_in_motion"),
        "cars_in_motion": _n("cars_in_motion"),
        "active_waybills": _n("active_waybills"),
        "avg_velocity_kmh": avg_kmh,
        "mql": format_operations([
            mql_aggregate("shipments", [{"$facet": {
                "trains_in_motion": [
                    {"$match": {"status": "in_transit"}},
                    {"$group": {"_id": "$current_train_symbol"}},
                    {"$count": "n"},
                ],
                "cars_in_motion": [
                    {"$match": {"status": "in_transit"}},
                    {"$count": "n"},
                ],
                "active_waybills": [
                    {"$match": {"status": {"$in": ["in_transit", "at_yard"]}}},
                    {"$count": "n"},
                ],
            }}]),
            mql_aggregate("events", velocity_pipeline),
        ]),
    }


@router.get("/pulse/cars_per_yard")
async def pulse_cars_per_yard():
    db = get_db()
    pipeline = [
        {"$match": {"status": "at_yard", "current_yard_code": {"$exists": True}}},
        {"$group": {"_id": "$current_yard_code", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 12},
        {"$lookup": {"from": "yards", "localField": "_id", "foreignField": "code", "as": "yard"}},
        {"$unwind": {"path": "$yard", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "yard_code": "$_id",
            "yard_name": {"$ifNull": ["$yard.name", "$_id"]},
            "city": "$yard.city",
            "state": "$yard.state",
            "count": 1,
        }},
    ]
    rows = await db.shipments.aggregate(pipeline).to_list(length=None)
    return {"rows": rows, "mql": format_operations([mql_aggregate("shipments", pipeline)])}


@router.get("/pulse/top_commodities")
async def pulse_top_commodities():
    db = get_db()
    pipeline = [
        {"$match": {"status": "in_transit"}},
        {"$group": {
            "_id": "$commodity_class",
            "count": {"$sum": 1},
            "hazmat": {"$sum": {"$cond": ["$hazmat", 1, 0]}},
        }},
        {"$sort": {"count": -1}},
        {"$project": {
            "_id": 0,
            "commodity_class": "$_id",
            "count": 1,
            "hazmat": 1,
        }},
    ]
    rows = await db.shipments.aggregate(pipeline).to_list(length=None)
    return {"rows": rows, "mql": format_operations([mql_aggregate("shipments", pipeline)])}


@router.get("/pulse/dwell_leaders")
async def pulse_dwell_leaders():
    """For each (equipment_id, yard_code), pair arrival/departure AEI events
    in chronological order and compute dwell minutes, then aggregate by yard."""
    db = get_db()
    pipeline = [
        {"$match": {"type": "AEI"}},
        {"$sort": {"equipment_id": 1, "raw.yard_code": 1, "ts": 1}},
        {"$group": {
            "_id": {"equipment_id": "$equipment_id", "yard_code": "$raw.yard_code"},
            "events": {"$push": {"ts": "$ts", "dir": "$raw.direction"}},
        }},
        {"$project": {
            "yard_code": "$_id.yard_code",
            "pairs": {
                "$reduce": {
                    "input": "$events",
                    "initialValue": {"open": None, "pairs": []},
                    "in": {
                        "$cond": [
                            {"$eq": ["$$this.dir", "arrival"]},
                            {"open": "$$this.ts", "pairs": "$$value.pairs"},
                            {
                                "open": None,
                                "pairs": {
                                    "$cond": [
                                        {"$ne": ["$$value.open", None]},
                                        {"$concatArrays": [
                                            "$$value.pairs",
                                            [{"$divide": [
                                                {"$subtract": ["$$this.ts", "$$value.open"]},
                                                60000,
                                            ]}],
                                        ]},
                                        "$$value.pairs",
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }},
        {"$unwind": "$pairs.pairs"},
        {"$group": {
            "_id": "$yard_code",
            "avg_min": {"$avg": "$pairs.pairs"},
            "max_min": {"$max": "$pairs.pairs"},
            "samples": {"$sum": 1},
        }},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"avg_min": -1}},
        {"$lookup": {"from": "yards", "localField": "_id", "foreignField": "code", "as": "yard"}},
        {"$unwind": {"path": "$yard", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "yard_code": "$_id",
            "yard_name": {"$ifNull": ["$yard.name", "$_id"]},
            "city": "$yard.city",
            "state": "$yard.state",
            "avg_min": {"$round": ["$avg_min", 1]},
            "max_min": {"$round": ["$max_min", 1]},
            "samples": 1,
        }},
        {"$limit": 12},
    ]
    rows = await db.events.aggregate(pipeline).to_list(length=None)
    return {"rows": rows, "mql": format_operations([mql_aggregate("events", pipeline)])}


@router.get("/pulse/train_velocity")
async def pulse_train_velocity():
    """Average km/h per train_symbol computed from GPS events in the last 2 hours."""
    db = get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    pipeline = [
        {"$match": {"type": "GPS", "ts": {"$gte": cutoff}}},
        {"$sort": {"train_symbol": 1, "ts": 1}},
        {"$group": {
            "_id": "$train_symbol",
            "coords": {"$push": "$location.coordinates"},
            "ts": {"$push": "$ts"},
            "n": {"$sum": 1},
        }},
        {"$match": {"n": {"$gte": 2}}},
    ]
    grouped = await db.events.aggregate(pipeline).to_list(length=None)

    from ..geo import haversine_km
    rows = []
    for r in grouped:
        coords = r["coords"]
        tss = r["ts"]
        dist_km = 0.0
        for i in range(1, len(coords)):
            dist_km += haversine_km(tuple(coords[i - 1]), tuple(coords[i]))
        hours = (tss[-1] - tss[0]).total_seconds() / 3600.0
        kmh = (dist_km / hours) if hours > 0 else 0.0
        rows.append({
            "train_symbol": r["_id"],
            "samples": r["n"],
            "km": round(dist_km, 1),
            "kmh": round(kmh, 1),
        })
    rows.sort(key=lambda r: r["kmh"], reverse=True)
    return {"rows": rows[:12], "mql": format_operations([mql_aggregate("events", pipeline)])}
