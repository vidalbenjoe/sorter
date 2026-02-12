"""Tests for config loading."""

import json
import tempfile
from pathlib import Path

import pytest

from photo_sorter.config import load_config, PointLocation, BoundsLocation, SorterConfig


def test_load_config_point(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "locations": [
            {"name": "Taipei 101", "point": {"lat": 25.0339, "lon": 121.5645}, "radius_km": 0.3}
        ],
        "base_output": "./out",
    }))
    config = load_config(cfg_path)
    assert len(config.locations) == 1
    assert isinstance(config.locations[0], PointLocation)
    assert config.locations[0].name == "Taipei 101"
    assert config.locations[0].lat == 25.0339
    assert config.locations[0].radius_km == 0.3
    assert config.base_output == "./out"


def test_load_config_bounds(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "locations": [
            {
                "name": "Jiufen",
                "bounds": {"min_lat": 25.108, "max_lat": 25.112, "min_lon": 121.843, "max_lon": 121.848}
            }
        ],
    }))
    config = load_config(cfg_path)
    assert len(config.locations) == 1
    assert isinstance(config.locations[0], BoundsLocation)
    assert config.locations[0].name == "Jiufen"
    assert config.locations[0].min_lat == 25.108


def test_load_config_uncategorized(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "locations": [],
        "uncategorized_behavior": "leave_in_place",
        "uncategorized_folder_name": "Unknown Location",
    }))
    config = load_config(cfg_path)
    assert config.uncategorized_behavior == "leave_in_place"
    assert config.uncategorized_folder_name == "Unknown Location"


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.json"))


def test_load_config_invalid_location_no_name(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "locations": [{"point": {"lat": 25, "lon": 121}}],
    }))
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_load_config_invalid_location_no_geometry(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "locations": [{"name": "X"}],
    }))
    with pytest.raises(ValueError):
        load_config(cfg_path)
