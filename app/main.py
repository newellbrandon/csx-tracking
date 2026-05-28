import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from .config import get_settings
from .db import close_client, get_client
from .routes import api, pages
from .sim import run_sim_forever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("csx")

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = get_client()
    try:
        await client.admin.command("ping")
        log.info("Connected to MongoDB at %s (db=%s)", settings.MONGODB_URI, settings.CSX_DEMO_DB)
    except PyMongoError as exc:
        log.error("Cannot reach MongoDB: %s", exc)
        raise

    sim_task = asyncio.create_task(run_sim_forever(), name="csx-sim")
    try:
        yield
    finally:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass
        close_client()


app = FastAPI(
    title="CSX Tracking Demo",
    description="MongoDB-backed CSX shipment tracking, operations, and network pulse.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(pages.router)
app.include_router(api.router, prefix="/api")
