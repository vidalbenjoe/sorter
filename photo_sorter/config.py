"""
Load and validate the locations config (JSON or YAML).

Copyright (c) 2026 Benjoe Vidal
Licensed under the MIT License.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json

# Optional YAML support
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@dataclass
class PointLocation:
    """A single lat/lon point (nearest-match within radius)."""
    name: str
    lat: float
    lon: float
    radius_km: float = 0.5  # default radius for point locations


@dataclass
class BoundsLocation:
    """A rectangular bounding box (min/max lat and lon)."""
    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


# Union type for a location definition
LocationDef = PointLocation | BoundsLocation


@dataclass
class SorterConfig:
    """Runtime configuration for the photo sorter."""
    locations: list[LocationDef] = field(default_factory=list)
    base_output: str = ""
    uncategorized_behavior: str = "folder"  # "folder" | "leave_in_place"
    uncategorized_folder_name: str = "Uncategorized"
    match_radius_km: float = 0.5  # default radius when using point locations


def _parse_location(raw: dict[str, Any]) -> LocationDef:
    """Parse one location entry from config into PointLocation or BoundsLocation."""
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Each location must have a non-empty 'name' string.")

    # Bounding box: min_lat, max_lat, min_lon, max_lon
    if "bounds" in raw:
        b = raw["bounds"]
        return BoundsLocation(
            name=name,
            min_lat=float(b["min_lat"]),
            max_lat=float(b["max_lat"]),
            min_lon=float(b["min_lon"]),
            max_lon=float(b["max_lon"]),
        )

    # Center + radius (point with radius)
    if "center" in raw:
        c = raw["center"]
        lat, lon = float(c["lat"]), float(c["lon"])
        radius_km = float(raw.get("radius_km", 0.5))
        return PointLocation(name=name, lat=lat, lon=lon, radius_km=radius_km)

    # Single point (use default or specified radius)
    if "point" in raw:
        p = raw["point"]
        lat, lon = float(p["lat"]), float(p["lon"])
        radius_km = float(raw.get("radius_km", 0.5))
        return PointLocation(name=name, lat=lat, lon=lon, radius_km=radius_km)

    # Legacy: top-level lat/lon
    if "lat" in raw and "lon" in raw:
        lat, lon = float(raw["lat"]), float(raw["lon"])
        radius_km = float(raw.get("radius_km", 0.5))
        return PointLocation(name=name, lat=lat, lon=lon, radius_km=radius_km)

    raise ValueError(
        f"Location '{name}' must define one of: point, center+radius_km, or bounds."
    )


def load_config(path: str | Path) -> SorterConfig:
    """
    Load config from a JSON or YAML file.
    Returns a SorterConfig. Raises on parse or validation errors.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".json",):
        data = json.loads(text)
    elif suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            raise ImportError("YAML config requires PyYAML. Install with: pip install PyYAML")
        data = yaml.safe_load(text)
    else:
        raise ValueError(f"Unsupported config format: {suffix}. Use .json or .yaml")

    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")

    locations: list[LocationDef] = []
    for item in data.get("locations", []):
        if not isinstance(item, dict):
            continue
        locations.append(_parse_location(item))

    base_output = data.get("base_output", "")
    if isinstance(base_output, str):
        base_output = base_output.strip()

    uncategorized_behavior = data.get("uncategorized_behavior", "folder")
    if uncategorized_behavior not in ("folder", "leave_in_place"):
        uncategorized_behavior = "folder"

    uncategorized_folder_name = data.get("uncategorized_folder_name", "Uncategorized")
    if not isinstance(uncategorized_folder_name, str):
        uncategorized_folder_name = "Uncategorized"

    return SorterConfig(
        locations=locations,
        base_output=base_output,
        uncategorized_behavior=uncategorized_behavior,
        uncategorized_folder_name=uncategorized_folder_name,
        match_radius_km=float(data.get("match_radius_km", 0.5)),
    )
