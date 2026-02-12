"""
Optional reverse geocoding: resolve (lat, lon) to a place name using a local
cache and Nominatim (OpenStreetMap) when cache misses. Keeps UX simple without
requiring the user to manually name folders.
"""

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

try:
    from unidecode import unidecode as _unidecode
except ImportError:
    def _unidecode(s: str) -> str:
        return "".join(c for c in s if ord(c) < 128)

# Cache key format: "lat,lon" rounded to 3 decimals (~100m)
COORD_PRECISION = 3
# Nominatim requires 1 request per second; we throttle
NOMINATIM_DELAY_SEC = 1.1
USER_AGENT = "PhotoSorter/1.0 (local photo organizer)"


def _cache_key(lat: float, lon: float, precision: Optional[int] = None) -> str:
    """Return a stable key for (lat, lon). Default precision=3 (~100m)."""
    p = COORD_PRECISION if precision is None else precision
    return f"{round(lat, p)},{round(lon, p)}"


def to_single_word_english(name: str) -> str:
    """
    Convert a place name to a single English word (PascalCase, ASCII only).
    Examples: "Taipei 101" -> "Taipei101", "Yehliu Geopark" -> "YehliuGeopark",
    "Jiufen, New Taipei" -> "JiufenNewTaipei". Non-ASCII is transliterated (e.g. 九份 -> Jiufen).
    
    If the result is mostly numbers (like a postal code), returns "Unknown" to trigger fallback.
    """
    if not name or not name.strip():
        return "Unknown"
    s = _unidecode(name)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = [p for p in s.split() if p and (p.isalpha() or p.isdigit())]
    if not parts:
        return "Unknown"
    
    # Filter out parts that are just short numbers (likely postal codes), but keep long numbers (e.g. 101)
    meaningful_parts = [p for p in parts if p.isalpha() or (p.isdigit() and len(p) > 3)]
    if not meaningful_parts:
        # If all parts are short numbers, this is probably a postal code - return Unknown
        return "Unknown"
    
    result = "".join(p.capitalize() if p.isalpha() else p for p in meaningful_parts)
    
    # If result is mostly numbers (more than 50% digits), treat as invalid
    if result and sum(c.isdigit() for c in result) > len(result) * 0.5:
        return "Unknown"
    
    return result if result else "Unknown"


def _name_to_safe_folder(name: str) -> str:
    """
    Fallback: turn any non-empty name into a safe folder name (single word style).
    Used when to_single_word_english returns Unknown but we still have a valid place name.
    """
    if not name or not name.strip():
        return "Unknown"
    s = _unidecode(name)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = [p for p in s.split() if p]
    if not parts:
        return "Unknown"
    # Take first few parts that look like words (not just digits)
    take = [p for p in parts if p.isalpha() or (p.isdigit() and len(p) > 2)][:4]
    if not take:
        return "Unknown"
    return "".join(p.capitalize() if p.isalpha() else p for p in take)


def cluster_precision_from_radius_km(radius_km: float) -> int:
    """Return decimal precision for lat/lon so cell size is ~2*radius_km. Used for clustering."""
    if radius_km <= 0:
        radius_km = 10.0
    if radius_km >= 50:
        return 0
    if radius_km >= 10:
        return 1
    if radius_km >= 2:
        return 2
    return 3


def cluster_key(lat: float, lon: float, radius_km: float) -> tuple[float, float]:
    """
    Return (lat_center, lon_center) so that all points within roughly radius_km
    of each other get the same key. Used to put nearby photos in the same folder.
    """
    p = cluster_precision_from_radius_km(radius_km)
    return (round(lat, p), round(lon, p))


def sanitize_folder_name(name: str) -> str:
    """Make a string safe for use as a folder name on Windows and common FS."""
    # Replace chars that are invalid or awkward in folder names
    replace = r'[\\/:*?"<>|]'
    out = re.sub(replace, " ", name)
    out = re.sub(r"\s+", " ", out).strip()
    return out or "Unknown"


def _load_cache(cache_path: Path) -> dict[str, str]:
    """Load cache from JSON file. Return dict mapping cache_key -> place_name."""
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache_path: Path, cache: dict[str, str]) -> None:
    """Write cache to JSON file."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_nominatim(lat: float, lon: float) -> Optional[str]:
    """
    Query Nominatim (OSM) for reverse geocoding. Returns a meaningful place name or None.
    Tries to extract a good place name from address components, falling back to display_name.
    Respects rate limit (caller should throttle).
    """
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?lat={lat}&lon={lon}&format=json&addressdetails=1"
    )
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as resp:
            status = resp.getcode()
            if status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict):
                return None
            
            # Check for error in response
            if "error" in data:
                return None
            
            # Try to get a meaningful place name from address components
            address = data.get("address", {})
            if isinstance(address, dict):
                # Prefer: tourist attraction, landmark, building
                for key in ["tourism", "landmark", "building", "attraction", "amenity"]:
                    if key in address and address[key]:
                        name = str(address[key])
                        city = address.get("city") or address.get("town") or address.get("village") or address.get("county")
                        if city and name != city:
                            return f"{name}, {city}"
                        return name
                
                # Prefer more specific place (village, neighbourhood) over city when top-level "name" is empty
                # Order: most specific first so we get "Sanzhangli" or "Jinglian Village" instead of just "Taipei"
                for key in ["village", "neighbourhood", "suburb", "town", "city", "county", "municipality", "state"]:
                    if key in address and address[key]:
                        name = str(address[key]).strip()
                        if not name:
                            continue
                        if name.isdigit() and len(name) <= 5:
                            continue  # skip postal code
                        return name
            
            # Last resort: use display_name (skip if it's only numbers/postal)
            display_name = data.get("display_name", "")
            if display_name:
                # Check if display_name is just a postal code or mostly numbers
                parts = display_name.split(",")
                # Take first meaningful part (not just numbers)
                for part in parts:
                    part = part.strip()
                    if part and not (part.isdigit() and len(part) <= 5):
                        return display_name  # Return full display_name if we found a non-numeric part
                # If all parts are numeric/short, return None to trigger fallback
                return None
            
            return None
    except URLError as e:
        # Network error (no connection, DNS, etc.)
        import logging
        logging.getLogger(__name__).debug("Nominatim network error for (%.4f, %.4f): %s", lat, lon, e.reason if getattr(e, "reason", None) else e)
        return None
    except HTTPError as e:
        # HTTP error (e.g. 429 rate limit, 503 service unavailable)
        import logging
        logging.getLogger(__name__).debug("Nominatim HTTP %s for (%.4f, %.4f)", e.code, lat, lon)
        return None
    except (OSError, json.JSONDecodeError, Exception) as e:
        import logging
        logging.getLogger(__name__).debug("Nominatim error for (%.4f, %.4f): %s", lat, lon, e)
        return None


# Module-level throttle: last request time
_last_request_time: float = 0


def get_place_name(
    lat: float,
    lon: float,
    cache_path: Optional[Path] = None,
    use_network: bool = True,
    single_word_english: bool = False,
    cache_precision: Optional[int] = None,
) -> str:
    """
    Get a human-readable place name for (lat, lon).

    - If cache_path is set and the key is in the cache, return cached name.
    - If use_network is True and cache misses, query Nominatim (rate-limited),
      cache the result, and return it.
    - Otherwise return a coordinate-based fallback.

    If single_word_english is True, the result is converted to PascalCase ASCII
    (e.g. Taiwan101, YehliuGeopark). cache_precision can be used when grouping
    by cluster (e.g. 1 for ~11 km) so the same cache key is used for the cluster.
    """
    key = _cache_key(lat, lon, cache_precision)
    fallback = f"{round(lat, COORD_PRECISION)}, {round(lon, COORD_PRECISION)}"
    if single_word_english:
        fallback = f"Lat{round(lat, 2)}Lon{round(lon, 2)}".replace(".", "_").replace("-", "_")

    if cache_path is not None:
        cache = _load_cache(cache_path)
        if key in cache:
            raw = cache[key]
            # Validate cached value - reject postal codes and coordinate-style fallbacks
            if raw and isinstance(raw, str):
                raw_stripped = raw.strip()
                # Reject if it looks like a coordinate fallback (from a failed geocode run)
                if raw_stripped.startswith("Lat") and "Lon" in raw_stripped:
                    cache.pop(key, None)
                    _save_cache(cache_path, cache)
                elif raw_stripped.isdigit() and 3 <= len(raw_stripped) <= 6:
                    cache.pop(key, None)
                    _save_cache(cache_path, cache)
                else:
                    # Valid cached value, use it
                    converted = to_single_word_english(raw) if single_word_english else sanitize_folder_name(raw)
                    if converted != "Unknown" or not single_word_english:
                        return converted
                    cache.pop(key, None)
                    _save_cache(cache_path, cache)

    if not use_network:
        return fallback

    # Rate limit
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < NOMINATIM_DELAY_SEC:
        time.sleep(NOMINATIM_DELAY_SEC - elapsed)
    _last_request_time = time.monotonic()

    import logging
    _log = logging.getLogger(__name__)
    _log.debug("Fetching place name for (%.4f, %.4f) from Nominatim...", lat, lon)

    name = _fetch_nominatim(lat, lon)
    if name:
        if single_word_english:
            converted = to_single_word_english(name)
            if converted == "Unknown":
                # Try fallback: build a safe folder name from the raw name (e.g. "Xinyi District" -> "XinyiDistrict")
                fallback_name = _name_to_safe_folder(name)
                if fallback_name != "Unknown":
                    _log.debug("Used fallback folder name for (%.4f, %.4f): %s (raw: %s)", lat, lon, fallback_name, name[:60])
                    if cache_path is not None:
                        cache = _load_cache(cache_path)
                        cache[key] = name
                        _save_cache(cache_path, cache)
                    return fallback_name
                _log.warning(
                    "Nominatim returned '%s' which could not be used for (%.4f, %.4f), using coordinates.",
                    name[:80] + ("..." if len(name) > 80 else ""), lat, lon
                )
                return fallback
            if cache_path is not None:
                cache = _load_cache(cache_path)
                cache[key] = name
                _save_cache(cache_path, cache)
            _log.debug("  -> %s", converted)
            return converted
        else:
            if cache_path is not None:
                cache = _load_cache(cache_path)
                cache[key] = name
                _save_cache(cache_path, cache)
            _log.debug("  -> %s", name)
            return sanitize_folder_name(name)

    _log.warning("Could not get place name for (%.4f, %.4f). Check internet. Using coordinate name.", lat, lon)
    return fallback


def rounded_coords_folder_name(lat: float, lon: float, single_word_english: bool = False) -> str:
    """Return a folder name based only on coordinates (no network)."""
    if single_word_english:
        return f"Lat{round(lat, 2)}Lon{round(lon, 2)}".replace(".", "_").replace("-", "_")
    return f"{round(lat, COORD_PRECISION)}, {round(lon, COORD_PRECISION)}"
