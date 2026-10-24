"""Tests for Module F: cheapest-compliant-design optimiser."""

from ananke.optimise.search import find_cheapest_designs, propellant_vs_altitude

# EO-DEMO-1 worked-example spacecraft parameters.
MASS_KG = 120
CD = 2.2
AREA_M2 = 1.2
ISP_S = 220


def test_cheapest_is_natural_decay_with_fuel():
    """With fuel available, the cheapest design is a zero-propellant natural-decay altitude."""
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=10,
        desired_altitude_km=750,
    )
    assert result["status"] == "OK", result
    top = result["candidates"][0]
    assert top["propellant_kg"] == 0.0, top
    assert top["altitude_km"] <= 510, top


def test_zero_fuel_only_natural_decay_candidates():
    """With no propellant, only natural-decay altitudes are feasible."""
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=0.0,
        desired_altitude_km=750,
    )
    assert result["status"] == "OK", result
    for c in result["candidates"]:
        assert c["propellant_kg"] == 0.0, c
        assert c["strategy"] == "natural_decay", c


def test_infeasible_when_no_compliant_altitude_and_no_fuel():
    """No naturally-compliant altitude in range + negligible fuel -> INFEASIBLE."""
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=0.001,
        desired_altitude_km=750,
        alt_min_km=600,
        alt_max_km=700,
    )
    assert result["status"] == "INFEASIBLE", result
    assert result["candidates"] == []


def test_respects_top_n():
    """No more than top_n candidates are returned."""
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=10,
        desired_altitude_km=750,
        top_n=2,
    )
    assert len(result["candidates"]) <= 2, result


def test_reports_total_candidates_evaluated_default_grid():
    """The default 400-1000 km grid at 10 km step reports 61 evaluated candidates.

    (1000 - 400) / 10 + 1 = 61, inclusive of both bounds. Pulled from the real
    grid the call used, never hardcoded inside find_cheapest_designs.
    """
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=10,
        desired_altitude_km=750,
    )
    assert "total_candidates_evaluated" in result
    assert result["total_candidates_evaluated"] == 61


def test_reports_total_candidates_evaluated_on_infeasible():
    """The count is reported on the INFEASIBLE path too (600-700 km at 10 km = 11)."""
    result = find_cheapest_designs(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s=ISP_S,
        propellant_available_kg=0.001,
        desired_altitude_km=750,
        alt_min_km=600,
        alt_max_km=700,
    )
    assert result["status"] == "INFEASIBLE", result
    assert result["total_candidates_evaluated"] == 11


def test_propellant_vs_altitude_shape_and_isp_ordering():
    """Trade-space data is well-formed and lower Isp never needs less fuel."""
    data = propellant_vs_altitude(
        mass_kg=MASS_KG,
        cd=CD,
        area_m2=AREA_M2,
        isp_s_list=[220, 60],
    )
    alts = data["altitudes_km"]
    by_isp = data["propellant_by_isp"]

    assert set(by_isp.keys()) == {220, 60}
    assert len(by_isp[220]) == len(alts)
    assert len(by_isp[60]) == len(alts)

    for p220, p60 in zip(by_isp[220], by_isp[60]):
        # Lower Isp needs >= fuel for the same burn; both 0 for natural decay.
        assert p60 >= p220, (p60, p220)
