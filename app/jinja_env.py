"""Shared Jinja2 environment with project filters."""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent.parent


def _tojson(value) -> str:
    return json.dumps(value).replace("<", "\\u003c")


env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)
env.filters["tojson"] = _tojson
