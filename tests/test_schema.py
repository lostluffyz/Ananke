"""Tests for the Ananke data schema."""

import pytest
from pydantic import ValidationError

from ananke.schema import MissionInput, ReentryPlan


def test_mission_input_parses_valid_sample():
    """A representative mission input parses without error."""
    data = {
        "name": "EO-DEMO-1",
        "mass_kg": 120,
        "area_m2": 1.2,
        "cd": 2.2,
        "orbit": {"type": "circular", "altitude_km": 750, "inclination_deg": 97.4},
        "mission_life_yr": 5,
        "propulsion": {
            "type": "monoprop",
            "isp_s": 220,
            "propellant_kg": 10,
            "reliability": 0.995,
        },
        "p_collision": 0.002,
        "disposal": {"strategy": "lower_to_circular", "target_alt_km": 500},
        "checklist": {"passivation": True, "trackable": True, "insurance": False},
    }

    mission = MissionInput(**data)

    assert mission.name == "EO-DEMO-1"
    assert mission.orbit.altitude_km == 750
    assert mission.propulsion.type.value == "monoprop"
    assert mission.disposal.strategy.value == "lower_to_circular"
    assert mission.checklist.insurance is False


def test_reentry_plan_rejects_out_of_range_latitude():
    """A target latitude outside [-90, 90] is invalid."""
    with pytest.raises(ValidationError):
        ReentryPlan(components=[{"mass_kg": 5.0, "area_m2": 0.5}], target_lat=95)


def test_reentry_plan_defaults_to_unknown_location():
    """No target coordinates (the default) validates and stays None."""
    plan = ReentryPlan(components=[{"mass_kg": 5.0, "area_m2": 0.5}])
    assert plan.target_lat is None
    assert plan.target_lon is None


def test_reentry_plan_accepts_valid_coordinates():
    """Valid coordinates (Mumbai) validate and are stored."""
    plan = ReentryPlan(
        components=[{"mass_kg": 5.0, "area_m2": 0.5}],
        target_lat=19.0760,
        target_lon=72.8777,
    )
    assert plan.target_lat == pytest.approx(19.0760)
    assert plan.target_lon == pytest.approx(72.8777)
