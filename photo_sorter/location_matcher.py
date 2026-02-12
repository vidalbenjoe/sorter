"""
Match (latitude, longitude) to user-defined locations (point+radius or bounding box).

Copyright (c) 2026 Benjoe Vidal
Licensed under the MIT License.
"""

import math
from typing import Optional

from .config import BoundsLocation, LocationDef, PointLocation, SorterConfig


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distance in kilometers between two points (WGS84), using Haversine formula.
    """
    R = 6371.0  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def point_in_bounds(lat: float, lon: float, loc: BoundsLocation) -> bool:
    """Return True if (lat, lon) is inside the bounding box."""
    return (
        loc.min_lat <= lat <= loc.max_lat
        and loc.min_lon <= lon <= loc.max_lon
    )


def match_point_location(
    lat: float, lon: float, loc: PointLocation
) -> tuple[bool, float]:
    """
    Check if (lat, lon) is within loc.radius_km of the point.
    Returns (matches: bool, distance_km: float).
    """
    d = haversine_km(lat, lon, loc.lat, loc.lon)
    return (d <= loc.radius_km, d)


def match_location(
    lat: float, lon: float, config: SorterConfig
) -> Optional[str]:
    """
    Determine which configured location (if any) the given coordinates belong to.

    Logic:
    - Bounds: if point falls inside any bounding box, that location is chosen (first match).
    - Point+radius: find the nearest point location within its radius; if multiple,
      choose the nearest one.

    Returns the folder name (location name) or None if no location matches.
    """
    if not config.locations:
        return None

    # First pass: check all bounds; first match wins
    for loc in config.locations:
        if isinstance(loc, BoundsLocation) and point_in_bounds(lat, lon, loc):
            return loc.name

    # Second pass: point locations — find nearest within radius
    best_name: Optional[str] = None
    best_dist_km: float = float("inf")

    for loc in config.locations:
        if isinstance(loc, PointLocation):
            matches, dist = match_point_location(lat, lon, loc)
            if matches and dist < best_dist_km:
                best_dist_km = dist
                best_name = loc.name

    return best_name
