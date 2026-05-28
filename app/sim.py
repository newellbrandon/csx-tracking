"""Background simulation: advance in-transit trains along their LineString routes.

Stateless: every tick re-reads trains + matching network_segments from MongoDB
and writes the advanced state back. No in-process cache of train positions.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import get_settings
from .db import get_db
from .geo import (
    interpolate_along,
    linestring_length_km,
    position_for,
    waypoint_progress,
)

log = logging.getLogger("csx.sim")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def _tick() -> dict[str, int]:
    """One sim tick. Returns counters for logging."""
    settings = get_settings()
    db = get_db()

    trains = await db.trains.find({"status": "in_transit"}).to_list(length=None)
    if not trains:
        return {"trains": 0, "gps": 0, "aei": 0, "delivered": 0}

    seg_ids = sorted({t["route_segment_id"] for t in trains})
    segments = await db.network_segments.find({"segment_id": {"$in": seg_ids}}).to_list(length=None)
    seg_by_id = {s["segment_id"]: s for s in segments}

    now = _now()
    events_to_insert: list[dict[str, Any]] = []
    gps_count = 0
    aei_count = 0

    for t in trains:
        seg = seg_by_id.get(t["route_segment_id"])
        if not seg:
            continue
        coords = seg["geometry"]["coordinates"]
        total_km = linestring_length_km(coords)
        if total_km <= 0:
            continue

        old_prog = float(t.get("progress", 0.0))
        direction = t.get("direction", "forward")
        delta = settings.SIM_STEP_KM / total_km
        new_prog = old_prog + delta
        flipped = False
        if new_prog >= 1.0:
            new_prog = max(0.0, min(1.0, 2.0 - new_prog))
            direction = "reverse" if direction == "forward" else "forward"
            flipped = True

        new_pos = position_for(new_prog, direction, coords)
        await db.trains.update_one(
            {"_id": t["_id"]},
            {"$set": {
                "progress": new_prog,
                "direction": direction,
                "current_position": {"type": "Point", "coordinates": [new_pos[0], new_pos[1]]},
                "updated_ts": now,
            }},
        )

        ships = await db.shipments.find(
            {"current_train_symbol": t["symbol"], "status": "in_transit"},
            {"current_equipment_id": 1, "waybill_number": 1},
        ).to_list(length=None)

        for ship in ships:
            events_to_insert.append({
                "ts": now,
                "type": "GPS",
                "equipment_id": ship["current_equipment_id"],
                "train_symbol": t["symbol"],
                "location": {"type": "Point", "coordinates": [new_pos[0], new_pos[1]]},
                "raw": {"source": "sim", "progress": new_prog, "direction": direction},
            })
            gps_count += 1

        if flipped:
            continue

        for wp_idx, wp in enumerate(seg["waypoints"]):
            yard_code = wp.get("yard_code")
            if not yard_code:
                continue
            line_prog = waypoint_progress(coords, wp_idx)
            wp_train_prog = (1.0 - line_prog) if direction == "reverse" else line_prog
            if not (old_prog < wp_train_prog <= new_prog):
                continue

            wp_lng, wp_lat = interpolate_along(coords, line_prog)
            dwell_minutes = random.uniform(8.0, 22.0)
            arrival_ts = now - timedelta(minutes=dwell_minutes)
            departure_ts = now

            for ship in ships:
                events_to_insert.append({
                    "ts": arrival_ts,
                    "type": "AEI",
                    "equipment_id": ship["current_equipment_id"],
                    "train_symbol": t["symbol"],
                    "location": {"type": "Point", "coordinates": [wp_lng, wp_lat]},
                    "raw": {"yard_code": yard_code, "direction": "arrival", "source": "sim"},
                })
                events_to_insert.append({
                    "ts": departure_ts,
                    "type": "AEI",
                    "equipment_id": ship["current_equipment_id"],
                    "train_symbol": t["symbol"],
                    "location": {"type": "Point", "coordinates": [wp_lng, wp_lat]},
                    "raw": {"yard_code": yard_code, "direction": "departure", "source": "sim"},
                })
                aei_count += 2

                await db.shipments.update_one(
                    {"_id": ship["_id"]},
                    {"$push": {"status_timeline": {
                        "ts": departure_ts,
                        "type": "STATUS",
                        "code": "AEI_SCAN",
                        "description": f"Passed {yard_code} yard ({dwell_minutes:.0f} min dwell)",
                        "location": yard_code,
                    }}},
                )

    if events_to_insert:
        await db.events.insert_many(events_to_insert)
    return {
        "trains": len(trains),
        "gps": gps_count,
        "aei": aei_count,
    }


async def run_sim_forever() -> None:
    settings = get_settings()
    log.info("sim started: interval=%.1fs step=%.1fkm", settings.SIM_INTERVAL_SECONDS, settings.SIM_STEP_KM)
    try:
        while True:
            try:
                counts = await _tick()
                if counts["trains"]:
                    log.debug("tick: %s", counts)
            except Exception:
                log.exception("sim tick failed; continuing")
            await asyncio.sleep(settings.SIM_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("sim cancelled")
        raise
