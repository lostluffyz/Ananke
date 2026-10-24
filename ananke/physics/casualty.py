"""Re-entry casualty risk (Module C).

When a satellite re-enters, some tough components (titanium/steel tanks, reaction
wheels, etc.) can survive to the ground. Each surviving fragment sweeps a "danger
patch" — the debris casualty area (DCA) — which accounts for the fragment's own
footprint plus the cross-section of a standing person:

    DCA_component = (0.6 + sqrt(A))^2   [m^2, with A the fragment area in m^2]

Summing over all surviving components gives the total DCA. The expected number of
casualties for an uncontrolled footprint is then:

    Ec = DCA (m^2) * 1e-6 * rho_eff (people/km^2)

where the 1e-6 converts DCA from m^2 to km^2.

Validation reference (NASA EUVE sanity check): DCA = 12.41 m^2 with an effective
population density rho_eff ~= 15 people/km^2 yields Ec ~= 1.86e-4, i.e. about
"1 in 5,300" — the published figure this module is checked against.
"""

from __future__ import annotations

import math


def debris_casualty_area(component_areas_m2: list[float]) -> float:
    """Total debris casualty area (DCA) for surviving fragments, in m^2.

    Computes ``sum((0.6 + sqrt(a))^2 for a in component_areas_m2)``.

    Parameters
    ----------
    component_areas_m2 : list[float]
        Cross-section areas of surviving fragments, in m^2. Must be non-empty
        and contain no negative values.

    Returns
    -------
    float
        Total DCA in m^2.

    Raises
    ------
    ValueError
        If the list is empty or any area is negative.
    """
    if not component_areas_m2:
        raise ValueError("component_areas_m2 must contain at least one area.")
    if any(a < 0 for a in component_areas_m2):
        raise ValueError("component areas must be non-negative.")
    return sum((0.6 + math.sqrt(a)) ** 2 for a in component_areas_m2)


def ec_uncontrolled(dca_m2: float, rho_eff_per_km2: float) -> float:
    """Expected casualties for an uncontrolled re-entry footprint (dimensionless).

    Ec = DCA (m^2) * 1e-6 * rho_eff (people/km^2). The 1e-6 converts the casualty
    area from m^2 to km^2 so it multiplies cleanly with the population density.

    Parameters
    ----------
    dca_m2 : float
        Total debris casualty area, in m^2.
    rho_eff_per_km2 : float
        Effective population density under the footprint, in people/km^2.

    Returns
    -------
    float
        Expected number of casualties (Ec).
    """
    return dca_m2 * 1e-6 * rho_eff_per_km2


def ec_with_failure(ec_nominal: float, ec_failure: float, p_fail: float) -> float:
    """Failure-weighted expected casualties (dimensionless).

    Blends the nominal (successful controlled re-entry) and failure (off-nominal
    footprint) casualty expectations by the manoeuvre failure probability:

        Ec_total = (1 - p_fail) * ec_nominal + p_fail * ec_failure

    Parameters
    ----------
    ec_nominal : float
        Expected casualties if the controlled re-entry succeeds.
    ec_failure : float
        Expected casualties if the manoeuvre fails (off-nominal footprint).
    p_fail : float
        Probability the controlled re-entry fails, in [0, 1].

    Returns
    -------
    float
        Failure-weighted expected casualties.

    Raises
    ------
    ValueError
        If ``p_fail`` is outside [0, 1].
    """
    if not (0.0 <= p_fail <= 1.0):
        raise ValueError(f"p_fail must be in [0, 1], got {p_fail!r}")
    return (1.0 - p_fail) * ec_nominal + p_fail * ec_failure
