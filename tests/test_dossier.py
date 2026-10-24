"""Tests for the dossier PDF generator.

reportlab PDFs are binary and awkward to assert content against, so these tests
only confirm the generator runs without error and produces a non-trivial file
across the four content branches (with/without optimiser, with/without lifetime,
OK vs INFEASIBLE optimiser results).
"""

import os

from ananke.optimise.search import find_cheapest_designs
from ananke.report.dossier import generate_dossier_pdf
from ananke.rules.engine import screen_mission
from ananke.schema import MissionInput

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


def _base_mission(**disposal_overrides) -> MissionInput:
    data = dict(BASE_MISSION)
    if disposal_overrides:
        data = dict(data)
        data["disposal"] = {**data["disposal"], **disposal_overrides}
    return MissionInput(**data)


def test_dossier_basic(tmp_path):
    """Base mission, no optimiser: returns path, file exists and is non-trivial."""
    mission = _base_mission()
    output = screen_mission(mission)
    path = str(tmp_path / "basic.pdf")

    result_path = generate_dossier_pdf(mission, output, optimiser_result=None, output_path=path)

    assert result_path == path
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000


def test_dossier_with_optimiser_ok(tmp_path):
    """Base mission with a real OK optimiser result: builds without error."""
    mission = _base_mission()
    output = screen_mission(mission)
    opt = find_cheapest_designs(
        mass_kg=120,
        cd=2.2,
        area_m2=1.2,
        isp_s=220,
        propellant_available_kg=10,
        desired_altitude_km=750,
    )
    assert opt["status"] == "OK"

    path = str(tmp_path / "with_opt.pdf")
    generate_dossier_pdf(mission, output, optimiser_result=opt, output_path=path)

    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000


def test_dossier_lifetime_none(tmp_path):
    """Mission with missing target: lifetime_years is None -> 'Not available' branch."""
    mission = _base_mission(target_alt_km=None)
    output = screen_mission(mission)
    assert output.lifetime_years is None

    path = str(tmp_path / "no_lifetime.pdf")
    generate_dossier_pdf(mission, output, optimiser_result=None, output_path=path)

    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000


def test_dossier_infeasible_optimiser(tmp_path):
    """INFEASIBLE optimiser result: prints the message branch without error."""
    mission = _base_mission()
    output = screen_mission(mission)
    opt = {"status": "INFEASIBLE", "candidates": [], "message": "test message"}

    path = str(tmp_path / "infeasible.pdf")
    generate_dossier_pdf(mission, output, optimiser_result=opt, output_path=path)

    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000
