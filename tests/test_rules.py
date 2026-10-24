"""Tests for the metrics layer and DFSM rule engine (R1, R2, R3, R5, R9)."""

import copy
import math

import pytest

from ananke.rules.engine import screen_mission
from ananke.rules.metrics import compute_metrics
from ananke.schema import MissionInput, RuleStatus

# Base worked-example mission from the design blueprint (EO-DEMO-1).
BASE_MISSION = {
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


def make_mission(**overrides) -> MissionInput:
    """Build a MissionInput from the base sample with deep-merged overrides."""
    data = copy.deepcopy(BASE_MISSION)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return MissionInput(**data)


def status_map(mission: MissionInput) -> dict:
    """Map rule id -> RuleStatus for a screened mission."""
    output = screen_mission(mission)
    return {r.id: r.status for r in output.rules}


def test_base_mission_all_pass():
    """Disposal to 500 km: R1, R2, R3, R5 all PASS (R9 needs a re-entry plan)."""
    statuses = status_map(make_mission())
    assert statuses["R1"] == RuleStatus.PASS, statuses
    assert statuses["R2"] == RuleStatus.PASS, statuses
    assert statuses["R3"] == RuleStatus.PASS, statuses
    assert statuses["R5"] == RuleStatus.PASS, statuses


def test_natural_decay_from_750_fails_r1():
    """Natural decay from 750 km: R1 FAIL (lifetime far over 5 yr), R5 PASS (no burn)."""
    mission = make_mission(disposal={"strategy": "natural_decay"})
    statuses = status_map(mission)
    assert statuses["R1"] == RuleStatus.FAIL, statuses
    assert statuses["R5"] == RuleStatus.PASS, statuses


def test_natural_decay_from_520_warns_r1():
    """Natural decay from 520 km: R1 WARN (worst-case fails, nominal passes)."""
    mission = make_mission(
        orbit={"altitude_km": 520},
        disposal={"strategy": "natural_decay"},
    )
    statuses = status_map(mission)
    assert statuses["R1"] == RuleStatus.WARN, statuses


def test_missing_target_alt_needs_input():
    """lower_to_circular with no target: R1 & R5 NEEDS_INPUT; R2 & R3 still evaluate."""
    mission = make_mission(
        disposal={"strategy": "lower_to_circular", "target_alt_km": None}
    )
    statuses = status_map(mission)
    assert statuses["R1"] == RuleStatus.NEEDS_INPUT, statuses
    assert statuses["R5"] == RuleStatus.NEEDS_INPUT, statuses
    assert statuses["R2"] == RuleStatus.PASS, statuses
    assert statuses["R3"] == RuleStatus.PASS, statuses


def test_band_crossing_flag_and_r3_fail():
    """Operating at 400 km sets band_crossing_flag=1.0 and R3 FAIL."""
    mission = make_mission(orbit={"altitude_km": 400})
    metrics = compute_metrics(mission)
    assert metrics["band_crossing_flag"] == 1.0, metrics
    assert status_map(mission)["R3"] == RuleStatus.FAIL


def test_high_collision_fails_r2():
    """High collision probability drops p_pmd below 0.99: R2 FAIL."""
    mission = make_mission(p_collision=0.05)
    metrics = compute_metrics(mission)
    assert metrics["p_pmd"] < 0.99, metrics
    assert status_map(mission)["R2"] == RuleStatus.FAIL


def test_r9_evaluates_for_controlled_reentry():
    """Controlled re-entry with a re-entry plan: R9 evaluates and ec_total matches by hand."""
    mission = make_mission(
        disposal={"strategy": "controlled_reentry", "target_alt_km": 0.0},
        reentry={"components": [{"mass_kg": 20.0, "area_m2": 2.0}]},
    )
    metrics = compute_metrics(mission)

    expected_dca = (0.6 + math.sqrt(2.0)) ** 2
    expected_ec = expected_dca * 1e-6 * 15.0  # default rho_eff, p_fail=0
    assert metrics["ec_total"] == pytest.approx(expected_ec), metrics

    r9 = status_map(mission)["R9"]
    assert r9 in (RuleStatus.PASS, RuleStatus.FAIL), r9


def test_r9_needs_input_without_reentry_plan():
    """Base mission (no re-entry planned): R9 is NEEDS_INPUT, which is correct."""
    assert status_map(make_mission())["R9"] == RuleStatus.NEEDS_INPUT
