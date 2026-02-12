"""Tests for geocoding helpers (cache key, sanitize, single-word, cluster)."""

import pytest

from photo_sorter.geocode import (
    _cache_key,
    cluster_key,
    cluster_precision_from_radius_km,
    sanitize_folder_name,
    to_single_word_english,
    rounded_coords_folder_name,
    get_place_name,
)


def test_cache_key():
    assert _cache_key(25.0339, 121.5645) == "25.034,121.565"
    assert _cache_key(0, 0) == "0.0,0.0"


def test_to_single_word_english():
    assert to_single_word_english("Taipei 101") == "Taipei101"
    assert to_single_word_english("Yehliu Geopark") == "YehliuGeopark"
    assert to_single_word_english("Jiufen, New Taipei") == "JiufenNewTaipei"
    assert to_single_word_english("Shifen Old Street") == "ShifenOldStreet"
    assert to_single_word_english("") == "Unknown"
    assert to_single_word_english("  ") == "Unknown"


def test_cluster_key_and_precision():
    # Same ~10 km area should get same cluster
    assert cluster_key(25.03, 121.56, 10) == (25.0, 121.6)
    assert cluster_key(25.05, 121.58, 10) == (25.1, 121.6)
    assert cluster_precision_from_radius_km(10) == 1
    assert cluster_precision_from_radius_km(5) == 2
    assert cluster_precision_from_radius_km(50) == 0


def test_sanitize_folder_name():
    assert sanitize_folder_name("Taipei 101") == "Taipei 101"
    assert sanitize_folder_name("a/b\\c") == "a b c"
    assert sanitize_folder_name('a:b*c?d"e') == "a b c d e"
    assert sanitize_folder_name("  spaces  ") == "spaces"
    assert sanitize_folder_name("") == "Unknown"


def test_rounded_coords_folder_name():
    assert rounded_coords_folder_name(25.0339, 121.5645) == "25.034, 121.565"
    assert rounded_coords_folder_name(0, 0) == "0.0, 0.0"
    assert rounded_coords_folder_name(25.03, 121.56, single_word_english=True) == "Lat25_03Lon121_56"


def test_get_place_name_offline():
    # No cache, no network -> fallback to coordinates
    name = get_place_name(25.034, 121.564, cache_path=None, use_network=False)
    assert name == "25.034, 121.564"
    name_sw = get_place_name(25.034, 121.564, cache_path=None, use_network=False, single_word_english=True)
    assert name_sw == "Lat25_03Lon121_56"
