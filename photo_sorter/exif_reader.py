"""
Read EXIF metadata and extract GPS latitude/longitude from image files.
Handles missing/corrupt EXIF and multiple image formats.
"""

from pathlib import Path
from typing import Optional

try:
    import piexif
except ImportError:
    piexif = None

# Optional HEIC support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _HEIC_AVAILABLE = True
except ImportError:
    _HEIC_AVAILABLE = False

from PIL import Image


# Supported image extensions (lowercase)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif"}


def _convert_to_degrees(value) -> float:
    """
    Convert EXIF rational (deg, min, sec) to decimal degrees.
    value is a tuple of (numerator, denominator) for each of deg, min, sec.
    Handles both rational tuples and direct float values.
    """
    if value is None:
        return 0.0
    
    # Handle direct float values (some EXIF readers may return already converted)
    if isinstance(value, (int, float)):
        return float(value)
    
    if not hasattr(value, "__iter__"):
        return 0.0
    
    # piexif returns tuples of (numerator, denominator) for each component
    try:
        # Handle case where value might be a list/tuple of tuples
        if len(value) < 3:
            return 0.0
        
        # Extract degrees
        if isinstance(value[0], (tuple, list)) and len(value[0]) >= 2:
            d = float(value[0][0]) / float(value[0][1]) if value[0][1] != 0 else float(value[0][0])
        else:
            d = float(value[0])
        
        # Extract minutes
        if isinstance(value[1], (tuple, list)) and len(value[1]) >= 2:
            m = float(value[1][0]) / float(value[1][1]) if value[1][1] != 0 else float(value[1][0])
        else:
            m = float(value[1])
        
        # Extract seconds
        if isinstance(value[2], (tuple, list)) and len(value[2]) >= 2:
            s = float(value[2][0]) / float(value[2][1]) if value[2][1] != 0 else float(value[2][0])
        else:
            s = float(value[2])
        
        return d + (m / 60.0) + (s / 3600.0)
    except (IndexError, TypeError, ZeroDivisionError, ValueError) as e:
        return 0.0


def _gps_from_piexif(file_path: Path) -> Optional[tuple[float, float]]:
    """
    Use piexif to load EXIF and extract GPS lat/lon.
    Returns (latitude, longitude) or None if not available.
    """
    if piexif is None:
        return None
    try:
        exif_dict = piexif.load(str(file_path))
    except Exception:
        return None

    gps = exif_dict.get("GPS")
    if not gps:
        return None

    # piexif.GPSIFD: LatitudeRef, Latitude, LongitudeRef, Longitude
    # Latitude: 1 = N, 2 = S; Longitude: 1 = E, 2 = W
    lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef)
    lat_val = gps.get(piexif.GPSIFD.GPSLatitude)
    lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef)
    lon_val = gps.get(piexif.GPSIFD.GPSLongitude)

    if not all([lat_ref, lat_val, lon_ref, lon_val]):
        return None

    try:
        lat = _convert_to_degrees(lat_val)
        lon = _convert_to_degrees(lon_val)
        
        # Check if conversion failed (returned 0.0 for both might indicate an issue)
        if lat == 0.0 and lon == 0.0:
            return None
    except (TypeError, IndexError, ValueError) as e:
        return None

    # Apply hemisphere signs
    if lat_ref in (b"S", "S", 2):
        lat = -lat
    if lon_ref in (b"W", "W", 2):
        lon = -lon

    # Sanity check - valid lat/lon ranges
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    return (lat, lon)


def _gps_from_pillow(file_path: Path) -> Optional[tuple[float, float]]:
    """
    Fallback: use Pillow's getexif() to read GPS if piexif failed or not installed.
    """
    try:
        img = Image.open(file_path)
        exif = img.getexif() if hasattr(img, "getexif") else None
        img.close()
    except Exception:
        return None

    if exif is None:
        return None

    # EXIF GPS tag 34853 is the GPS IFD; we'd need to parse it manually.
    # Pillow doesn't expose GPS as a simple (lat, lon). So we rely on piexif
    # as primary. This fallback is minimal and can be extended.
    return None


def get_gps_from_image(file_path: str | Path) -> Optional[tuple[float, float]]:
    """
    Extract GPS (latitude, longitude) from an image file's EXIF data.

    Handles:
    - No EXIF: returns None
    - No GPS in EXIF: returns None
    - Corrupted or partial metadata: returns None (no exception)

    Supported formats: JPEG, PNG, HEIC (if pillow-heif installed), TIFF.

    Args:
        file_path: Path to the image file.

    Returns:
        (latitude, longitude) as decimal degrees, or None if unavailable.
    """
    path = Path(file_path)
    if not path.is_file():
        return None

    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return None

    if suffix in (".heic", ".heif") and not _HEIC_AVAILABLE:
        return None

    # Prefer piexif (more reliable for EXIF/GPS)
    coords = _gps_from_piexif(path)
    if coords is not None:
        return coords

    return _gps_from_pillow(path)


def is_image_file(path: str | Path) -> bool:
    """Return True if the path has a supported image extension."""
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS
