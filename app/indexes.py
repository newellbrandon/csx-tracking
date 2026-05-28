"""Index creation. No Atlas Search / Vector Search needed in this revision."""
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, GEOSPHERE

log = logging.getLogger("csx.indexes")


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.yards.create_index([("location", GEOSPHERE)], name="yards_location_2dsphere")
    await db.yards.create_index([("code", ASCENDING)], unique=True, name="yards_code_uniq")

    await db.industries.create_index([("location", GEOSPHERE)], name="industries_location_2dsphere")
    await db.industries.create_index([("code", ASCENDING)], unique=True, name="industries_code_uniq")
    await db.industries.create_index([("customer_code", ASCENDING)], name="industries_customer")
    await db.industries.create_index([("served_by_yard", ASCENDING)], name="industries_served_by_yard")

    await db.customers.create_index([("code", ASCENDING)], unique=True, name="customers_code_uniq")
    await db.customers.create_index([("hq", GEOSPHERE)], name="customers_hq_2dsphere")

    await db.network_segments.create_index([("geometry", GEOSPHERE)], name="net_geometry_2dsphere")
    await db.network_segments.create_index([("segment_id", ASCENDING)], unique=True, name="net_segment_uniq")

    await db.railcars.create_index([("equipment_id", ASCENDING)], unique=True, name="railcars_eq_uniq")
    await db.railcars.create_index(
        [("hazmat", ASCENDING), ("car_type", ASCENDING)],
        name="railcars_hazmat_type",
    )
    await db.railcars.create_index([("commodity_class", ASCENDING)], name="railcars_commodity_class")

    await db.trains.create_index([("symbol", ASCENDING)], unique=True, name="trains_symbol_uniq")
    await db.trains.create_index([("current_position", GEOSPHERE)], name="trains_pos_2dsphere")
    await db.trains.create_index([("status", ASCENDING)], name="trains_status")

    await db.shipments.create_index([("waybill_number", ASCENDING)], unique=True, name="ship_waybill_uniq")
    await db.shipments.create_index([("current_equipment_id", ASCENDING)], name="ship_equipment")
    await db.shipments.create_index(
        [("current_train_symbol", ASCENDING), ("status", ASCENDING)],
        name="ship_train_status",
    )
    await db.shipments.create_index(
        [("status", ASCENDING), ("commodity_class", ASCENDING)],
        name="ship_status_commodity",
    )
    await db.shipments.create_index([("hazmat", ASCENDING)], name="ship_hazmat")

    await db.events.create_index([("equipment_id", ASCENDING), ("ts", DESCENDING)], name="events_eq_ts")
    await db.events.create_index([("train_symbol", ASCENDING), ("ts", DESCENDING)], name="events_train_ts")
    await db.events.create_index([("location", GEOSPHERE)], name="events_loc_2dsphere")
    await db.events.create_index([("type", ASCENDING)], name="events_type")

    log.info("indexes ensured")


async def ensure_events_timeseries(db: AsyncIOMotorDatabase) -> None:
    existing = await db.list_collection_names(filter={"name": "events"})
    if existing:
        return
    await db.create_collection(
        "events",
        timeseries={
            "timeField": "ts",
            "metaField": "equipment_id",
            "granularity": "seconds",
        },
    )
    log.info("events time-series collection created")
