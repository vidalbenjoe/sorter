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
    "Jiufen, New Taipei" -> "JiufenNewTaipei". Non-ASCII is transliterated (e.g. 九份 -> Jiufen, 民雄鄉 -> Minxiong Xiang).
    
    If the result is mostly numbers (like a postal code), returns "Unknown" to trigger fallback.
    """
    if not name or not name.strip():
        return "Unknown"
    
    # Transliterate Chinese/other non-ASCII characters first (e.g. 民雄鄉 -> Minxiong Xiang)
    s = _unidecode(name)
    
    # Remove punctuation, keep alphanumeric and spaces
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    
    # Split into parts (words/numbers)
    parts = [p for p in s.split() if p]
    if not parts:
        return "Unknown"
    
    # Filter: keep alphabetic words and longer numbers (e.g. "101" but not "110")
    meaningful_parts = []
    for p in parts:
        if p.isalpha():
            meaningful_parts.append(p)
        elif p.isdigit() and len(p) > 3:  # Keep numbers like "101" but skip postal codes like "110"
            meaningful_parts.append(p)
    
    if not meaningful_parts:
        return "Unknown"
    
    # Build PascalCase result
    result = "".join(p.capitalize() if p.isalpha() else p for p in meaningful_parts)
    
    # If result is mostly numbers (more than 50% digits), treat as invalid
    if result and sum(c.isdigit() for c in result) > len(result) * 0.5:
        return "Unknown"
    
    return result if result else "Unknown"


def _name_to_safe_folder(name: str) -> str:
    """
    Fallback: turn any non-empty name into a safe folder name (single word style).
    Used when to_single_word_english returns Unknown but we still have a valid place name.
    Handles Chinese characters better by being very lenient - accepts any transliterated result.
    """
    if not name or not name.strip():
        return "Unknown"
    
    # Transliterate Chinese/other non-ASCII (e.g. 民雄鄉 -> Minxiong Xiang)
    s = _unidecode(name)
    
    # If transliteration produced empty or only punctuation, try a different approach
    if not s or not s.strip():
        # If unidecode failed completely, try using pinyin-like approach or just use first few chars
        # For now, return Unknown so caller can try village/suburb
        return "Unknown"
    
    # Remove punctuation, keep alphanumeric and spaces
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    
    if not s:
        return "Unknown"
    
    parts = [p for p in s.split() if p]
    if not parts:
        return "Unknown"
    
    # Very lenient: take ANY parts that aren't just short numbers (postal codes)
    take = []
    for p in parts:
        # Skip only if it's a short number (likely postal code)
        if p.isdigit() and len(p) <= 5:
            continue
        take.append(p)
        if len(take) >= 4:  # Limit to 4 parts max
            break
    
    if not take:
        # If all parts were short numbers, try using the original transliterated string
        cleaned = re.sub(r"[^\w]", "", s)
        if cleaned and len(cleaned) > 2:
            return cleaned.capitalize()
        return "Unknown"
    
    # Build PascalCase: capitalize first letter of each part
    result_parts = []
    for p in take:
        if p:
            # Capitalize first letter, keep rest as-is
            result_parts.append(p[0].upper() + p[1:].lower() if len(p) > 1 else p.upper())
    
    result = "".join(result_parts)
    return result if result and len(result) > 1 else "Unknown"


def _has_chinese_characters(text: str) -> bool:
    """
    Check if text contains Chinese characters (CJK Unified Ideographs).
    Returns True if any character is in the Chinese character range.
    """
    if not text:
        return False
    for char in text:
        # CJK Unified Ideographs: U+4E00 to U+9FFF
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False


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


def _fetch_nominatim(lat: float, lon: float) -> tuple[Optional[str], Optional[dict]]:
    """
    Query Nominatim (OSM) for reverse geocoding. Returns (place_name, address_dict) or (None, None).
    Tries to extract a good place name from address components, falling back to display_name.
    Also returns the address dict so caller can check village/suburb as fallback.
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
                return None, None
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict):
                return None, None
            
            # Check for error in response
            if "error" in data:
                return None, None
            
            address = data.get("address", {})
            
            # Try to get a meaningful place name from address components
            if isinstance(address, dict):
                # Prefer: tourist attraction, landmark, building
                for key in ["tourism", "landmark", "building", "attraction", "amenity"]:
                    if key in address and address[key]:
                        name = str(address[key])
                        city = address.get("city") or address.get("town") or address.get("village") or address.get("county")
                        if city and name != city:
                            return f"{name}, {city}", address
                        return name, address
                
                # Collect suburb and village first (user preference)
                suburb_name = None
                village_name = None
                for key in ["suburb", "village"]:
                    if key in address and address[key]:
                        name = str(address[key]).strip()
                        if not name or (name.isdigit() and len(name) <= 5):
                            continue
                        if key == "suburb":
                            suburb_name = name
                        elif key == "village":
                            village_name = name
                
                # Collect town and city_district (common in Taiwan)
                town_name = None
                city_district_name = None
                for key in ["town", "city_district"]:
                    if key in address and address[key]:
                        name = str(address[key]).strip()
                        if not name or (name.isdigit() and len(name) <= 5):
                            continue
                        if key == "town":
                            town_name = name
                        elif key == "city_district":
                            city_district_name = name
                
                # Priority: suburb > village > (town/city_district only if NOT Chinese, or if no suburb/village)
                # If town/city_district has Chinese, prefer English suburb/village instead
                if suburb_name:
                    # Check if suburb has Chinese - if so, prefer village if it's English
                    if _has_chinese_characters(suburb_name) and village_name and not _has_chinese_characters(village_name):
                        return village_name, address
                    return suburb_name, address
                
                if village_name:
                    return village_name, address
                
                # Use town/city_district, but prefer English over Chinese
                if town_name:
                    # If town has Chinese and we have English city_district, prefer city_district
                    if _has_chinese_characters(town_name) and city_district_name and not _has_chinese_characters(city_district_name):
                        return city_district_name, address
                    return town_name, address
                
                if city_district_name:
                    return city_district_name, address
                
                # Fallback: neighbourhood, city, county, etc.
                for key in ["neighbourhood", "city", "county", "municipality", "state"]:
                    if key in address and address[key]:
                        name = str(address[key]).strip()
                        if not name:
                            continue
                        if name.isdigit() and len(name) <= 5:
                            continue  # skip postal code
                        return name, address, address
            
            # Last resort: use display_name (skip if it's only numbers/postal)
            display_name = data.get("display_name", "")
            if display_name:
                # Check if display_name is just a postal code or mostly numbers
                parts = display_name.split(",")
                # Take first meaningful part (not just numbers)
                for part in parts:
                    part = part.strip()
                    if part and not (part.isdigit() and len(part) <= 5):
                        return display_name, address  # Return full display_name if we found a non-numeric part
                # If all parts are numeric/short, return None to trigger fallback
                return None, address
            
            return None, address
    except URLError as e:
        # Network error (no connection, DNS, etc.)
        import logging
        logging.getLogger(__name__).debug("Nominatim network error for (%.4f, %.4f): %s", lat, lon, e.reason if getattr(e, "reason", None) else e)
        return None, None
    except HTTPError as e:
        # HTTP error (e.g. 429 rate limit, 503 service unavailable)
        import logging
        logging.getLogger(__name__).debug("Nominatim HTTP %s for (%.4f, %.4f)", e.code, lat, lon)
        return None, None
    except (OSError, json.JSONDecodeError, Exception) as e:
        import logging
        logging.getLogger(__name__).debug("Nominatim error for (%.4f, %.4f): %s", lat, lon, e)
        return None, None


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

    name, address_dict = _fetch_nominatim(lat, lon)
    if name:
        if single_word_english:
            converted = to_single_word_english(name)
            if converted == "Unknown":
                # Try fallback: build a safe folder name from the raw name
                fallback_name = _name_to_safe_folder(name)
                if fallback_name != "Unknown":
                    _log.debug("Used fallback folder name for (%.4f, %.4f): %s (raw: %s)", lat, lon, fallback_name, name[:60])
                    if cache_path is not None:
                        cache = _load_cache(cache_path)
                        cache[key] = name
                        _save_cache(cache_path, cache)
                    return fallback_name
                
                # If conversion failed and name has Chinese characters, check village/suburb from address
                if _has_chinese_characters(name) and address_dict:
                    for fallback_key in ["village", "suburb"]:
                        if fallback_key in address_dict and address_dict[fallback_key]:
                            fallback_value = str(address_dict[fallback_key]).strip()
                            if fallback_value and not (fallback_value.isdigit() and len(fallback_value) <= 5):
                                # Try converting the fallback value
                                fallback_converted = to_single_word_english(fallback_value)
                                if fallback_converted != "Unknown":
                                    _log.debug("Used %s '%s' instead of Chinese name for (%.4f, %.4f)", fallback_key, fallback_converted, lat, lon)
                                    if cache_path is not None:
                                        cache = _load_cache(cache_path)
                                        cache[key] = fallback_value
                                        _save_cache(cache_path, cache)
                                    return fallback_converted
                                # Even if conversion fails, try the safe folder fallback
                                safe_fallback = _name_to_safe_folder(fallback_value)
                                if safe_fallback != "Unknown":
                                    _log.debug("Used %s '%s' (safe fallback) instead of Chinese name for (%.4f, %.4f)", fallback_key, safe_fallback, lat, lon)
                                    if cache_path is not None:
                                        cache = _load_cache(cache_path)
                                        cache[key] = fallback_value
                                        _save_cache(cache_path, cache)
                                    return safe_fallback
                
                # Show what unidecode produces for debugging
                transliterated = _unidecode(name)
                _log.warning(
                    "Nominatim returned '%s' (transliterated: '%s') which could not be used for (%.4f, %.4f), using coordinates.",
                    name[:60] + ("..." if len(name) > 60 else ""),
                    transliterated[:60] + ("..." if len(transliterated) > 60 else ""),
                    lat, lon
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
    
    # If name is None but we have address_dict, try village/suburb as last resort
    if name is None and address_dict:
        for fallback_key in ["village", "suburb"]:
            if fallback_key in address_dict and address_dict[fallback_key]:
                fallback_value = str(address_dict[fallback_key]).strip()
                if fallback_value and not (fallback_value.isdigit() and len(fallback_value) <= 5):
                    if single_word_english:
                        converted = to_single_word_english(fallback_value)
                        if converted != "Unknown":
                            _log.debug("Used %s '%s' as fallback for (%.4f, %.4f)", fallback_key, converted, lat, lon)
                            if cache_path is not None:
                                cache = _load_cache(cache_path)
                                cache[key] = fallback_value
                                _save_cache(cache_path, cache)
                            return converted
                    else:
                        _log.debug("Used %s '%s' as fallback for (%.4f, %.4f)", fallback_key, fallback_value, lat, lon)
                        if cache_path is not None:
                            cache = _load_cache(cache_path)
                            cache[key] = fallback_value
                            _save_cache(cache_path, cache)
                        return sanitize_folder_name(fallback_value)

    _log.warning("Could not get place name for (%.4f, %.4f). Check internet. Using coordinate name.", lat, lon)
    return fallback


def rounded_coords_folder_name(lat: float, lon: float, single_word_english: bool = False) -> str:
    """Return a folder name based only on coordinates (no network)."""
    if single_word_english:
        return f"Lat{round(lat, 2)}Lon{round(lon, 2)}".replace(".", "_").replace("-", "_")
    return f"{round(lat, COORD_PRECISION)}, {round(lon, COORD_PRECISION)}"
