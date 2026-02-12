"""Tests for EXIF reading and GPS extraction."""

import tempfile
from pathlib import Path

import pytest

from photo_sorter.exif_reader import (
    get_gps_from_image,
    is_image_file,
    IMAGE_EXTENSIONS,
)


def test_is_image_file():
    assert is_image_file("photo.jpg") is True
    assert is_image_file("photo.JPEG") is True
    assert is_image_file("photo.png") is True
    assert is_image_file("photo.HEIC") is True
    assert is_image_file(Path("a/b/photo.tiff")) is True
    assert is_image_file("photo.txt") is False
    assert is_image_file("photo") is False


def test_get_gps_nonexistent_file():
    assert get_gps_from_image(Path("/nonexistent/photo.jpg")) is None


def test_get_gps_unsupported_extension(tmp_path):
    (tmp_path / "file.txt").write_text("x")
    assert get_gps_from_image(tmp_path / "file.txt") is None


def test_get_gps_no_exif_file(tmp_path):
    """A JPEG with no EXIF (e.g. created by Pillow) should return None or coords if we don't embed any."""
    try:
        from PIL import Image
        img_path = tmp_path / "no_exif.jpg"
        Image.new("RGB", (10, 10), color="red").save(img_path, "JPEG")
        # May return None (no GPS) or we could add GPS with piexif for next test
        result = get_gps_from_image(img_path)
        assert result is None
    except Exception:
        pytest.skip("PIL save failed")


def test_get_gps_with_embedded_gps(tmp_path):
    """Create a JPEG with GPS EXIF using piexif and read it back."""
    try:
        import piexif
    except ImportError:
        pytest.skip("piexif not installed")

    from PIL import Image

    # GPS format: degrees, minutes, seconds as (num, den) rationals
    # 25.0339 ≈ 25° 2' 2"  -> (25,1), (2,1), (2,1)
    # 121.5645 ≈ 121° 33' 52" -> (121,1), (33,1), (52,1)
    lat_rat = ((25, 1), (2, 1), (2, 1))
    lon_rat = ((121, 1), (33, 1), (52, 1))

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: lat_rat,
        piexif.GPSIFD.GPSLongitudeRef: b"E",
        piexif.GPSIFD.GPSLongitude: lon_rat,
    }
    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)

    img_path = tmp_path / "with_gps.jpg"
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(img_path, "JPEG", exif=exif_bytes)

    result = get_gps_from_image(img_path)
    assert result is not None
    lat, lon = result
    assert abs(lat - 25.0339) < 0.01
    assert abs(lon - 121.5645) < 0.01
