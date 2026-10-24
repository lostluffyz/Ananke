"""Cheapest-compliant-design search (Module F).

Rather than making the user guess altitudes, this module sweeps a range of
operational altitudes (holding mass / area / Cd / propulsion fixed) and, for
each, decides whether natural decay already satisfies the 5-year rule or an
active disposal burn is needed. Every candidate is judged under the WORST-CASE
solar scenario (k=0.5, slow decay) so the recommendation is robust rather than
optimistic.

    - If a candidate altitude already decays within 5 years worst-case, it needs
      no burn (natural decay, zero propellant).
    - Otherwise the satellite must be lowered to the altitude whose worst-case
      lifetime is exactly 5 years; the propellant for that Hohmann burn (plus a
      margin) is charged against the mission's available propellant.
    - Candidates that would need more propellant than is available are excluded.
    - If nothing in the search range is both compliant and fuel-feasible, the
      result is reported as INFEASIBLE rather than a false pass.
"""

from __future__ import annotations

from ananke.physics.deltav import hohmann_dv_ms, propellant_mass_kg
from ananke.physics.lifetime import (
    altitude_for_lifetime,
    ballistic_coefficient,
    lifetime_years,
)

# Worst-case solar-activity multiplier and the 5-year disposal target (years).
WORST_CASE_K = 0.5
FIVE_YEAR_LIMIT = 5.0


def _altitude_grid(alt_min_km: float, alt_max_km: float, alt_step_km: float) -> list[float]:
    """Inclusive altitude grid from ``alt_min_km`` to ``alt_max_km`` (km).

    Built by integer step count to avoid floating-point drift, and inclusive of
    the upper bound (mirrors ``range(min, max + 1, step)``).
    """
    n = int(round((alt_max_km - alt_min_km) / alt_step_km)) + 1
    return [alt_min_km + i * alt_step_km for i in range(n)]


def find_cheapest_designs(
    mass_kg: float,
    cd: float,
    area_m2: float,
    isp_s: float,
    propellant_available_kg: float,
    desired_altitude_km: float,
    alt_min_km: float = 400.0,
    alt_max_km: float = 1000.0,
    alt_step_km: float = 10.0,
    dv_margin: float = 1.2,
    top_n: int = 3,
) -> dict:
    """Search altitudes for the cheapest compliant, fuel-feasible design.

    Parameters
    ----------
    mass_kg, cd, area_m2 : float
        Spacecraft mass (kg), drag coefficient, and cross-section area (m^2).
    isp_s : float
        Propulsion specific impulse (s), used to price disposal burns.
    propellant_available_kg : float
        Propellant actually carried; candidates needing more are rejected.
    desired_altitude_km : float
        The operator's preferred altitude; used only as a tie-break (closer is
        better when propellant cost is equal).
    alt_min_km, alt_max_km, alt_step_km : float
        Altitude search grid bounds and step (km).
    dv_margin : float
        Multiplier applied to the ideal disposal delta-v (default 1.2 = 20%).
    top_n : int
        Maximum number of candidates to return.

    Returns
    -------
    dict
        ``{"status": "OK", "candidates": [...], "message": None}`` with up to
        ``top_n`` candidates sorted by propellant (then deviation), or
        ``{"status": "INFEASIBLE", "candidates": [], "message": ...}`` if no
        altitude in range is compliant and fuel-feasible. Both paths also carry
        ``"total_candidates_evaluated"``: the number of altitude grid points
        actually searched in this call.
    """
    B = ballistic_coefficient(mass_kg, cd, area_m2)

    # The disposal altitude (worst-case 5-year lifetime) depends only on B, so
    # compute it once rather than per-altitude.
    h_disposal = altitude_for_lifetime(B, FIVE_YEAR_LIMIT, k=WORST_CASE_K)

    # Build the altitude grid once so we both iterate it and report its true size
    # (the number of design candidates actually evaluated in this call).
    grid = _altitude_grid(alt_min_km, alt_max_km, alt_step_km)
    total_candidates_evaluated = len(grid)

    candidates: list[dict] = []
    for h in grid:
        worst_life = lifetime_years(h, B, k=WORST_CASE_K)

        if worst_life < FIVE_YEAR_LIMIT:
            # Natural decay already satisfies the rule: no burn required.
            candidates.append(
                {
                    "altitude_km": h,
                    "strategy": "natural_decay",
                    "propellant_kg": 0.0,
                    "deviation_km": abs(h - desired_altitude_km),
                    "worst_life_years": worst_life,
                }
            )
        else:
            # Needs an active burn down to the 5-year disposal altitude.
            dv = hohmann_dv_ms(h, h_disposal)
            prop = propellant_mass_kg(mass_kg, dv * dv_margin, isp_s)
            if prop > propellant_available_kg:
                # Not enough fuel for this candidate; exclude it.
                continue
            candidates.append(
                {
                    "altitude_km": h,
                    "strategy": f"burn to {h_disposal:.0f} km",
                    "propellant_kg": prop,
                    "deviation_km": abs(h - desired_altitude_km),
                    "worst_life_years": worst_life,
                }
            )

    if not candidates:
        return {
            "status": "INFEASIBLE",
            "candidates": [],
            "total_candidates_evaluated": total_candidates_evaluated,
            "message": (
                "No altitude in the search range produces a compliant, "
                "fuel-feasible design. Consider a lower search floor, more "
                "propellant, a higher-Isp thruster, or controlled re-entry."
            ),
        }

    # Cheapest propellant first; break ties by proximity to the desired altitude.
    candidates.sort(key=lambda c: (c["propellant_kg"], c["deviation_km"]))
    return {
        "status": "OK",
        "candidates": candidates[:top_n],
        "total_candidates_evaluated": total_candidates_evaluated,
        "message": None,
    }


def propellant_vs_altitude(
    mass_kg: float,
    cd: float,
    area_m2: float,
    isp_s_list: list[float],
    alt_min_km: float = 450.0,
    alt_max_km: float = 800.0,
    alt_step_km: float = 10.0,
    dv_margin: float = 1.2,
) -> dict:
    """Trade-space data: disposal propellant vs operational altitude, per Isp.

    For each altitude in the grid, computes the propellant needed to lower the
    satellite to the worst-case 5-year disposal altitude, for each specific
    impulse in ``isp_s_list``. Altitudes that already decay within 5 years
    worst-case need no burn (0 propellant, for every Isp).

    Returns
    -------
    dict
        ``{"altitudes_km": [...], "propellant_by_isp": {isp: [...]}}`` where each
        propellant list is aligned index-for-index with ``altitudes_km``.
    """
    B = ballistic_coefficient(mass_kg, cd, area_m2)
    h_disposal = altitude_for_lifetime(B, FIVE_YEAR_LIMIT, k=WORST_CASE_K)

    altitudes = _altitude_grid(alt_min_km, alt_max_km, alt_step_km)
    propellant_by_isp: dict[float, list[float]] = {isp: [] for isp in isp_s_list}

    for h in altitudes:
        worst_life = lifetime_years(h, B, k=WORST_CASE_K)
        naturally_compliant = worst_life < FIVE_YEAR_LIMIT
        dv = 0.0 if naturally_compliant else hohmann_dv_ms(h, h_disposal)
        for isp in isp_s_list:
            prop = 0.0 if naturally_compliant else propellant_mass_kg(
                mass_kg, dv * dv_margin, isp
            )
            propellant_by_isp[isp].append(prop)

    return {"altitudes_km": altitudes, "propellant_by_isp": propellant_by_isp}
