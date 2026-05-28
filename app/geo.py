"""Pure geometry helpers used by seed.py, sim.py, and routes.

No I/O, no MongoDB, no caches. Stateless math only.
"""
from __future__ import annotations

import math
from typing import Iterable

EARTH_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in kilometers between [lng,lat] pairs."""
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def linestring_length_km(coords: list[list[float]]) -> float:
    return sum(haversine_km(tuple(coords[i]), tuple(coords[i + 1])) for i in range(len(coords) - 1))


def cumulative_lengths_km(coords: list[list[float]]) -> list[float]:
    out = [0.0]
    for i in range(len(coords) - 1):
        out.append(out[-1] + haversine_km(tuple(coords[i]), tuple(coords[i + 1])))
    return out


def interpolate_along(coords: list[list[float]], progress: float) -> tuple[float, float]:
    """Linear interpolate along a LineString. `progress` in [0,1]."""
    progress = max(0.0, min(1.0, progress))
    if len(coords) < 2:
        return tuple(coords[0])  # type: ignore[return-value]
    cum = cumulative_lengths_km(coords)
    total = cum[-1]
    target = progress * total
    for i in range(len(cum) - 1):
        if target <= cum[i + 1]:
            seg_len = cum[i + 1] - cum[i]
            f = 0.0 if seg_len == 0 else (target - cum[i]) / seg_len
            ax = coords[i]
            bx = coords[i + 1]
            return (ax[0] + (bx[0] - ax[0]) * f, ax[1] + (bx[1] - ax[1]) * f)
    return tuple(coords[-1])  # type: ignore[return-value]


def nearest_waypoint_index(coords: list[list[float]], point: tuple[float, float]) -> int:
    best = 0
    best_d = float("inf")
    for i, c in enumerate(coords):
        d = haversine_km((c[0], c[1]), point)
        if d < best_d:
            best_d = d
            best = i
    return best


def waypoint_progress(coords: list[list[float]], waypoint_index: int) -> float:
    cum = cumulative_lengths_km(coords)
    total = cum[-1]
    if total == 0:
        return 0.0
    return cum[waypoint_index] / total


def reverse_progress(progress: float, direction: str) -> float:
    return 1.0 - progress if direction == "reverse" else progress


def directed_progress(progress: float, direction: str) -> float:
    """Convert a [0,1] progress along a route into the position along the
    underlying LineString, honoring direction."""
    return reverse_progress(progress, direction)


def position_for(progress: float, direction: str, coords: list[list[float]]) -> tuple[float, float]:
    return interpolate_along(coords, directed_progress(progress, direction))


def linestring_coords(geojson_linestring: dict) -> list[list[float]]:
    return list(geojson_linestring["coordinates"])


def first_at_or_after(values: Iterable[float], threshold: float) -> int | None:
    for i, v in enumerate(values):
        if v >= threshold:
            return i
    return None
