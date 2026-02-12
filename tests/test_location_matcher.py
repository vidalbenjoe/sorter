"""Tests for location matching logic."""

import pytest

from photo_sorter.config import (
    BoundsLocation,
    PointLocation,
    SorterConfig,
)
from photo_sorter.location_matcher import (
    haversine_km,
    point_in_bounds,
    match_point_location,
    match_location,
)


def test_haversine_km():
    # Same point -> 0
    assert haversine_km(0, 0, 0, 0) == 0.0
    # Known approx: Taipei 101 to Shifen ~20 km
    d = haversine_km(25.0339, 121.5645, 25.0426, 121.7762)
    assert 15 < d < 25


def test_point_in_bounds():
    loc = BoundsLocation(
        name="Box",
        min_lat=25.0,
        max_lat=26.0,
        min_lon=121.0,
        max_lon=122.0,
    )
    assert point_in_bounds(25.5, 121.5, loc) is True
    assert point_in_bounds(25.0, 121.0, loc) is True
    assert point_in_bounds(24.9, 121.5, loc) is False
    assert point_in_bounds(25.5, 122.1, loc) is False


def test_match_point_location():
    loc = PointLocation(name="Taipei", lat=25.034, lon=121.564, radius_km=0.5)
    match, dist = match_point_location(25.034, 121.564, loc)
    assert match is True
    assert dist <= 0.01

    match, dist = match_point_location(25.04, 121.57, loc)
    assert match is True
    assert dist < 1.0

    match, dist = match_point_location(25.5, 121.5, loc)
    assert match is False
    assert dist > 50


def test_match_location_empty_config():
    config = SorterConfig(locations=[])
    assert match_location(25.0, 121.0, config) is None


def test_match_location_bounds_first():
    config = SorterConfig(
        locations=[
            BoundsLocation("Jiufen", 25.108, 25.112, 121.843, 121.848),
            PointLocation("Other", 25.11, 121.845, radius_km=0.5),
        ]
    )
    # Inside Jiufen bounds
    assert match_location(25.11, 121.845, config) == "Jiufen"


def test_match_location_point_within_radius():
    config = SorterConfig(
        locations=[
            PointLocation("Taipei 101", 25.0339, 121.5645, radius_km=0.3),
        ]
    )
    assert match_location(25.034, 121.565, config) == "Taipei 101"
    assert match_location(25.05, 121.56, config) is None  # too far


def test_match_location_nearest_point_wins():
    config = SorterConfig(
        locations=[
            PointLocation("A", 25.033, 121.564, radius_km=1.0),
            PointLocation("B", 25.034, 121.565, radius_km=1.0),
        ]
    )
    # Closer to B
    result = match_location(25.0345, 121.565, config)
    assert result == "B"
