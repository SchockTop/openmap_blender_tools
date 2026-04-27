"""Unit tests for waypoint_generators (pure-Python, uses pyproj)."""
import math
import pytest


@pytest.fixture
def munich_bbox():
    # ~ 4x2 km Munich-Sued corridor in UTM32N
    return (688000.0, 5332000.0, 692000.0, 5334000.0)


def test_each_generator_returns_correct_count(munich_bbox):
    from blender_tools.waypoint_generators import (
        s_curve_diagonal, ground_snake, straight_through,
        orbit_around_center, banking_diagonal, descending_approach,
    )
    assert len(s_curve_diagonal(munich_bbox, 1500.0)) == 30
    assert len(ground_snake(munich_bbox, 1.7)) == 30
    assert len(straight_through(munich_bbox, 1.7)) == 30
    assert len(orbit_around_center(munich_bbox, 80.0)) == 60
    assert len(banking_diagonal(munich_bbox, 2000.0)) == 40
    assert len(descending_approach(munich_bbox, 4500.0)) == 40


def test_all_waypoints_are_in_lat_lon_range(munich_bbox):
    """Generated lat/lon should fall in Munich region."""
    from blender_tools.waypoint_generators import PRESET_GENERATORS
    for name, gen in PRESET_GENERATORS.items():
        pts = gen(munich_bbox, 100.0)
        for lat, lon, alt in pts:
            assert 47.5 < lat < 49.0, f"{name}: lat {lat}"
            assert 11.0 < lon < 12.5, f"{name}: lon {lon}"


def test_descending_approach_actually_descends(munich_bbox):
    from blender_tools.waypoint_generators import descending_approach
    pts = descending_approach(munich_bbox, 4500.0, descent_factor=0.5)
    assert pts[0][2] == pytest.approx(4500.0, rel=0.01)
    assert pts[-1][2] == pytest.approx(2250.0, rel=0.01)
    # Monotonic descent
    alts = [p[2] for p in pts]
    for i in range(1, len(alts)):
        assert alts[i] <= alts[i-1] + 0.001  # allow tiny float wobble


def test_orbit_returns_to_start(munich_bbox):
    from blender_tools.waypoint_generators import orbit_around_center
    pts = orbit_around_center(munich_bbox, 80.0)
    # First and last points should be ~equal (full circle).
    assert pts[0][0] == pytest.approx(pts[-1][0], abs=1e-4)
    assert pts[0][1] == pytest.approx(pts[-1][1], abs=1e-4)


def test_generate_waypoints_for_preset_dispatches(munich_bbox):
    from blender_tools.waypoint_generators import generate_waypoints_for_preset
    pts_walk = generate_waypoints_for_preset("fpv-walk", munich_bbox)
    pts_aircraft = generate_waypoints_for_preset("aircraft-approach", munich_bbox)
    # FPV-walk has tight altitude (1.7m), aircraft 4500m.
    assert all(p[2] < 5 for p in pts_walk)
    assert all(p[2] > 1000 for p in pts_aircraft)


def test_generate_waypoints_for_unknown_preset_falls_back(munich_bbox):
    from blender_tools.waypoint_generators import generate_waypoints_for_preset
    # Unknown preset -> should fall back to s_curve_diagonal (30 points).
    pts = generate_waypoints_for_preset("does-not-exist", munich_bbox, altitude_agl_m=100.0)
    assert len(pts) == 30
