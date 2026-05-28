"""Format MongoDB operations for display (mongosh-style Extended JSON)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import get_settings


def _json_body(obj: Any, indent: int = 2) -> str:
    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            if o.tzinfo is None:
                o = o.replace(tzinfo=timezone.utc)
            return {"$date": o.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    return json.dumps(obj, indent=indent, default=_default)


def mql_find(
    collection: str,
    filter_doc: dict[str, Any],
    *,
    projection: dict[str, Any] | None = None,
    sort: list[tuple[str, int]] | dict[str, int] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if projection is not None:
        opts["projection"] = projection
    if sort is not None:
        opts["sort"] = sort if isinstance(sort, dict) else dict(sort)
    if limit is not None:
        opts["limit"] = limit
    return {
        "database": get_settings().CSX_DEMO_DB,
        "collection": collection,
        "operation": "find",
        "filter": filter_doc,
        "options": opts or None,
    }


def mql_aggregate(collection: str, pipeline: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "database": get_settings().CSX_DEMO_DB,
        "collection": collection,
        "operation": "aggregate",
        "pipeline": pipeline,
    }


def format_operation(op: dict[str, Any]) -> str:
    """Render one operation as a mongosh snippet."""
    db = op["database"]
    coll = op["collection"]
    if op["operation"] == "find":
        parts = [f"db.getSiblingDB('{db}').{coll}.find(\n  {_json_body(op['filter'])}"]
        opts = op.get("options") or {}
        if opts.get("projection"):
            parts.append(f",\n  {_json_body(opts['projection'])}")
        closing = "\n)"
        if opts.get("sort"):
            closing = f"\n).sort({_json_body(opts['sort'])})"
        if opts.get("limit") is not None:
            if ".sort(" in closing:
                closing = closing[:-1] + f".limit({opts['limit']})"
            else:
                closing = f"\n).limit({opts['limit']})"
        return "".join(parts) + closing

    if op["operation"] == "aggregate":
        return (
            f"db.getSiblingDB('{db}').{coll}.aggregate(\n"
            f"{_json_body(op['pipeline'])}\n)"
        )

    return _json_body(op)


def format_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Return structured MQL payload for API responses."""
    return {
        "database": operations[0]["database"] if operations else get_settings().CSX_DEMO_DB,
        "operations": operations,
        "shell": "\n\n".join(format_operation(o) for o in operations),
    }
