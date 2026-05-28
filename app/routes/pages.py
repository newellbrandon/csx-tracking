from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from ..jinja_env import env

templates = Jinja2Templates(env=env)

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"active": "home"})


@router.get("/track")
async def track(request: Request, id: str | None = None):
    ctx: dict = {"active": "track", "ident": id or ""}
    if id:
        from ..db import get_db
        db = get_db()
        ident = id.strip().upper()
        ship = await db.shipments.find_one({
            "$or": [
                {"waybill_number": ident},
                {"current_equipment_id": ident},
            ]
        }, {"waybill_number": 1, "current_equipment_id": 1})
        ctx["found"] = ship is not None
        if ship:
            ctx["ident"] = ship["waybill_number"]
    return templates.TemplateResponse(request, "track.html", ctx)


@router.get("/ops")
async def ops(request: Request):
    return templates.TemplateResponse(request, "ops.html", {"active": "ops"})


@router.get("/pulse")
async def pulse(request: Request):
    return templates.TemplateResponse(request, "pulse.html", {"active": "pulse"})
