"""Disposal delta-v and propellant budgeting.

To move a satellite from one orbit to a lower one for disposal, the spacecraft
must change its velocity by some amount, delta-v (Δv). This module provides the
two Δv models we need, plus the rocket equation that turns a Δv budget into a
propellant mass.

    - Hohmann transfer: two burns, circular orbit to circular orbit. Used when
      lowering the whole orbit to a lower circular altitude.
    - Perigee lowering: a single burn at apogee that drops only the perigee.
      Used for the "lower perigee" disposal strategy (e.g. to speed up decay).

The rocket equation then relates Δv to the propellant mass required for a given
engine specific impulse (Isp).

All Δv values are returned in m/s; masses in kg.
"""

from __future__ import annotations

import numpy as np

# Reuse the same gravitational parameter and Earth radius as the lifetime model
# so the two physics modules stay numerically consistent.
from ananke.physics.lifetime import MU as MU_KM  # km^3/s^2
from ananke.physics.lifetime import RE as RE_KM  # km

# Standard sea-level gravity used by the rocket equation (m/s^2).
G0 = 9.80665

_KM_S_TO_M_S = 1000.0


def _circular_speed_km_s(r_km: float) -> float:
    """Circular orbital speed at radius ``r_km`` (km from Earth's centre), in km/s."""
    return np.sqrt(MU_KM / r_km)


def hohmann_dv_ms(h1_km: float, h2_km: float) -> float:
    """Total Hohmann-transfer Δv between two circular altitudes, in m/s.

    Computes the two-burn Δv to move between circular orbits at altitudes
    ``h1_km`` and ``h2_km`` (km above Earth's surface). The result is
    order-independent: transferring 750->500 gives the same magnitude as
    500->750.

    Parameters
    ----------
    h1_km, h2_km : float
        Circular-orbit altitudes above Earth's surface, in km.

    Returns
    -------
    float
        Total Δv (first burn + second burn), in m/s.
    """
    r1 = RE_KM + h1_km
    r2 = RE_KM + h2_km

    dv1 = abs(_circular_speed_km_s(r1) * (np.sqrt(2.0 * r2 / (r1 + r2)) - 1.0))
    dv2 = abs(_circular_speed_km_s(r2) * (1.0 - np.sqrt(2.0 * r1 / (r1 + r2))))

    dv_total_km_s = dv1 + dv2
    return float(dv_total_km_s * _KM_S_TO_M_S)


def perigee_lowering_dv_ms(h1_km: float, target_perigee_km: float) -> float:
    """Single-burn Δv to lower perigee from a circular orbit, in m/s.

    Starting from a circular orbit at altitude ``h1_km``, a single burn at that
    point (which becomes the new apogee) lowers the perigee to
    ``target_perigee_km``. Returns the burn magnitude in m/s.

    Parameters
    ----------
    h1_km : float
        Starting circular-orbit altitude (km), which becomes the apogee.
    target_perigee_km : float
        Desired perigee altitude after the burn (km).

    Returns
    -------
    float
        Δv magnitude for the single perigee-lowering burn, in m/s.
    """
    r1 = RE_KM + h1_km
    rp = RE_KM + target_perigee_km
    a_t = (r1 + rp) / 2.0  # semi-major axis of the transfer ellipse

    # Speed at apogee r1 on the transfer ellipse via the vis-viva equation.
    v_transfer_apogee = np.sqrt(MU_KM * (2.0 / r1 - 1.0 / a_t))
    dv_km_s = _circular_speed_km_s(r1) - v_transfer_apogee
    return float(dv_km_s * _KM_S_TO_M_S)


def propellant_mass_kg(m0_kg: float, dv_ms: float, isp_s: float) -> float:
    """Propellant mass required for a Δv burn, in kg (Tsiolkovsky rocket equation).

    propellant = m0 * (1 - exp(-dv / (Isp * g0)))

    Parameters
    ----------
    m0_kg : float
        Initial (wet) spacecraft mass before the burn, in kg.
    dv_ms : float
        Delta-v to be provided by the burn, in m/s.
    isp_s : float
        Engine specific impulse, in seconds.

    Returns
    -------
    float
        Propellant mass consumed, in kg.
    """
    return float(m0_kg * (1.0 - np.exp(-dv_ms / (isp_s * G0))))


def propellant_fraction(m0_kg: float, dv_ms: float, isp_s: float) -> float:
    """Propellant mass as a fraction of initial mass (dimensionless, 0-1).

    Equivalent to :func:`propellant_mass_kg` divided by ``m0_kg``:
    ``1 - exp(-dv / (Isp * g0))``.

    Parameters
    ----------
    m0_kg : float
        Initial (wet) spacecraft mass, in kg.
    dv_ms : float
        Delta-v to be provided by the burn, in m/s.
    isp_s : float
        Engine specific impulse, in seconds.

    Returns
    -------
    float
        Propellant mass fraction (propellant_mass / m0).
    """
    return float(propellant_mass_kg(m0_kg, dv_ms, isp_s) / m0_kg)
