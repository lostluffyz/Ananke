"""Derive the metrics the rule engine needs from a mission description.

:func:`compute_metrics` is the bridge between the raw :class:`MissionInput` and
the DFSM rule engine. It calls the physics modules (lifetime, delta-v,
reliability) and returns a flat dict of scalar metrics. Any metric that cannot
be computed because a required input is missing is returned as ``None`` (the
key is always present so the engine can flag it as NEEDS_INPUT).
"""

from __future__ import annotations

from ananke.physics.deltav import (
    hohmann_dv_ms,
    perigee_lowering_dv_ms,
    propellant_mass_kg,
)
from ananke.physics.casualty import (
    debris_casualty_area,
    ec_uncontrolled,
    ec_with_failure,
)
from ananke.physics.lifetime import ballistic_coefficient, lifetime_range
from ananke.physics.reliability import p_pmd
from ananke.schema import MissionInput

# Fraction of extra propellant budgeted on top of the ideal disposal delta-v.
DV_MARGIN = 1.2

# Human-spaceflight protected altitude band (km), inclusive bounds.
HUMAN_BAND_LO_KM = 370.0
HUMAN_BAND_HI_KM = 430.0


def _in_human_band(alt_km: float) -> bool:
    """True if an altitude falls inside the 370-430 km human-spaceflight band."""
    return HUMAN_BAND_LO_KM <= alt_km <= HUMAN_BAND_HI_KM


def compute_metrics(mission: MissionInput) -> dict:
    """Compute all rule-engine metrics for a mission.

    Returns a dict with exactly these keys (any un-computable value is None):
        lifetime_worst_after_disposal, lifetime_nominal_after_disposal,
        lifetime_best_after_disposal, p_pmd, band_crossing_flag,
        required_dv_ms, required_propellant_kg, propellant_available_kg,
        fuel_margin_kg
    """
    # 1. Ballistic coefficient (kg/m^2).
    B = ballistic_coefficient(mission.mass_kg, mission.cd, mission.area_m2)

    # 2-3. Operational altitude and its (pre-disposal) lifetime band.
    op_alt = mission.orbit.altitude_km
    lifetime_op = lifetime_range(op_alt, B)  # noqa: F841 (kept for clarity/future use)

    # 4. Post-disposal altitude and required delta-v, per disposal strategy.
    strategy = mission.disposal.strategy.value
    target = mission.disposal.target_alt_km

    if strategy == "natural_decay":
        # No manoeuvre: the satellite stays where it is and decays naturally.
        post_alt = op_alt
        required_dv_ms = 0.0
    elif strategy == "lower_to_circular":
        if target is None:
            post_alt = None
            required_dv_ms = None
        else:
            post_alt = target
            required_dv_ms = hohmann_dv_ms(op_alt, target)
    elif strategy == "lower_perigee":
        if target is None:
            post_alt = None
            required_dv_ms = None
        else:
            # MVP simplification: treat the lowered perigee as an equivalent
            # circular altitude for the lifetime estimate. A proper elliptical
            # decay model would average over the orbit; that refinement is
            # deferred.
            post_alt = target
            required_dv_ms = perigee_lowering_dv_ms(op_alt, target)
    elif strategy == "controlled_reentry":
        if target is None:
            post_alt = None
            required_dv_ms = None
        else:
            # Treated as immediate disposal (lifetime = 0). The delta-v is
            # approximated by a Hohmann transfer to the target for now; a real
            # controlled re-entry burn model arrives with Module C later.
            post_alt = 0.0
            required_dv_ms = hohmann_dv_ms(op_alt, target)
    else:  # pragma: no cover - schema enum prevents this
        raise ValueError(f"Unknown disposal strategy: {strategy!r}")

    # 5. Post-disposal lifetime band.
    if post_alt is None:
        lifetime_post = {"best": None, "nominal": None, "worst": None}
    elif post_alt == 0.0:
        lifetime_post = {"best": 0.0, "nominal": 0.0, "worst": 0.0}
    else:
        lifetime_post = lifetime_range(post_alt, B)

    # 6. Required propellant (with margin) via the rocket equation.
    if required_dv_ms is None:
        required_propellant_kg = None
    else:
        required_propellant_kg = propellant_mass_kg(
            mission.mass_kg, required_dv_ms * DV_MARGIN, mission.propulsion.isp_s
        )

    # 7. Propellant availability and margin.
    propellant_available_kg = mission.propulsion.propellant_kg
    if required_propellant_kg is None:
        fuel_margin_kg = None
    else:
        fuel_margin_kg = propellant_available_kg - required_propellant_kg

    # 8. Post-mission disposal success probability.
    p_pmd_value = p_pmd(mission.propulsion.reliability, mission.p_collision)

    # 9. Human-spaceflight band crossing (operational or post-disposal altitude).
    band_crossing = _in_human_band(op_alt) or (
        post_alt is not None and _in_human_band(post_alt)
    )
    band_crossing_flag = 1.0 if band_crossing else 0.0

    # 10. Re-entry expected casualties (only meaningful for controlled re-entry).
    if mission.disposal.strategy.value == "controlled_reentry" and mission.reentry is not None:
        areas = [c.area_m2 for c in mission.reentry.components]
        dca = debris_casualty_area(areas)
        ec_nominal = ec_uncontrolled(dca, mission.reentry.nominal_rho_eff_per_km2)
        ec_failure = ec_uncontrolled(dca, mission.reentry.failure_rho_eff_per_km2)
        ec_total = ec_with_failure(ec_nominal, ec_failure, mission.reentry.p_fail)
    else:
        # No re-entry planned: casualty risk is not applicable / cannot be computed.
        ec_total = None

    # 11. Flat metrics dict.
    return {
        "lifetime_worst_after_disposal": lifetime_post["worst"],
        "lifetime_nominal_after_disposal": lifetime_post["nominal"],
        "lifetime_best_after_disposal": lifetime_post["best"],
        "p_pmd": p_pmd_value,
        "band_crossing_flag": band_crossing_flag,
        "required_dv_ms": required_dv_ms,
        "required_propellant_kg": required_propellant_kg,
        "propellant_available_kg": propellant_available_kg,
        "fuel_margin_kg": fuel_margin_kg,
        "ec_total": ec_total,
    }
