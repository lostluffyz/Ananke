"""Orbital lifetime of a circular-orbit satellite due to atmospheric drag.

A satellite in a low circular orbit loses energy to drag and slowly spirals in.
This module estimates how many years it takes to decay from a starting altitude
down to a re-entry altitude (~120 km, where it effectively burns up).

Physics (circular-orbit approximation)
--------------------------------------
    circular speed        v = sqrt(mu / r)
    period                T = 2*pi*sqrt(r^3 / mu)
    ballistic coefficient B = mass / (Cd * A)                     [kg/m^2]
    decay rate            da/dt = -rho(h) * sqrt(mu * a) / B

Lifetime is the time to fall from h0 down to h_re, obtained by integrating the
inverse decay rate over altitude:

    lifetime = integral_{h_re}^{h0} dh / ( rho(h)/B * sqrt(mu * (RE + h)) )

The integral is evaluated numerically with a fine altitude step (midpoint rule).
The integration is carried out in SI units (metres, kg, seconds) so that the
kg/m^3 densities from :mod:`ananke.physics.atmosphere` combine consistently.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from ananke.physics.atmosphere import rho

# Earth gravitational parameter (km^3/s^2) and mean equatorial radius (km).
MU = 398600.4418
RE = 6378.137
YEAR_SECONDS = 365.25 * 86400

# Unit conversions used inside the SI integration.
_MU_SI = MU * 1e9  # km^3/s^2 -> m^3/s^2  (1 km^3 = 1e9 m^3)
_KM_TO_M = 1000.0


def circular_speed_km_s(altitude_km: float) -> float:
    """Circular orbital speed at ``altitude_km`` (km), in km/s.

    v = sqrt(mu / r), with r = RE + altitude.
    """
    r = RE + altitude_km
    return float(np.sqrt(MU / r))


def orbital_period_min(altitude_km: float) -> float:
    """Orbital period of a circular orbit at ``altitude_km`` (km), in minutes.

    T = 2*pi*sqrt(r^3 / mu), with r = RE + altitude; converted from s to min.
    """
    r = RE + altitude_km
    period_s = 2.0 * np.pi * np.sqrt(r**3 / MU)
    return float(period_s / 60.0)


def ballistic_coefficient(mass_kg: float, cd: float, area_m2: float) -> float:
    """Ballistic coefficient B = mass / (Cd * A), in kg/m^2.

    Higher B means the object is less affected by drag (decays slower).
    """
    return float(mass_kg / (cd * area_m2))


def lifetime_years(
    altitude_km: float,
    B: float,
    k: float = 1.0,
    h_re_km: float = 120.0,
    dh_km: float = 0.5,
) -> float:
    """Years to decay from ``altitude_km`` down to ``h_re_km`` due to drag.

    Numerically integrates ``dt = dh / (da/dt)`` from the re-entry altitude up to
    the starting altitude using the midpoint rule with step ``dh_km`` (km).

    Parameters
    ----------
    altitude_km : float
        Starting circular-orbit altitude (km).
    B : float
        Ballistic coefficient mass / (Cd * A), in kg/m^2.
    k : float
        Solar-activity density multiplier passed to the atmosphere model
        (1.0 nominal, 2.0 high/best-case, 0.5 low/worst-case).
    h_re_km : float
        Re-entry altitude at which the object is considered gone (km).
    dh_km : float
        Integration step in altitude (km); smaller is more accurate.

    Returns
    -------
    float
        Estimated orbital lifetime in years. Returns 0.0 if the starting
        altitude is already at or below the re-entry altitude.
    """
    if altitude_km <= h_re_km:
        return 0.0

    # Midpoints of each dh_km slice between h_re_km and altitude_km.
    lower_edges = np.arange(h_re_km, altitude_km, dh_km)
    h_mid = lower_edges + dh_km / 2.0
    # Clip midpoints so the final (possibly partial) slice stays below the start.
    h_mid = np.minimum(h_mid, altitude_km)

    r_m = (RE + h_mid) * _KM_TO_M
    density = rho(h_mid, k)  # kg/m^3, array-valued
    # da/dt magnitude (m/s): rho * sqrt(mu * r) / B, all in SI.
    dadt = density * np.sqrt(_MU_SI * r_m) / B
    dt = (dh_km * _KM_TO_M) / dadt  # seconds to fall each slice

    total_seconds = float(np.sum(dt))
    return total_seconds / YEAR_SECONDS


def lifetime_range(altitude_km: float, B: float) -> dict:
    """Lifetime estimate band for a circular orbit, in years.

    Returns a dict with keys:
        "best"    -> k = 2.0 (high solar activity, fastest decay, shortest life)
        "nominal" -> k = 1.0 (nominal atmosphere)
        "worst"   -> k = 0.5 (low solar activity, slowest decay, longest life)
    """
    return {
        "best": lifetime_years(altitude_km, B, k=2.0),
        "nominal": lifetime_years(altitude_km, B, k=1.0),
        "worst": lifetime_years(altitude_km, B, k=0.5),
    }


def altitude_for_lifetime(
    B: float,
    target_years: float,
    k: float = 1.0,
    lo_km: float = 150.0,
    hi_km: float = 2000.0,
) -> float:
    """Circular altitude (km) whose drag lifetime equals ``target_years``.

    Solves ``lifetime_years(h, B, k) == target_years`` for altitude ``h`` by
    bisection over ``[lo_km, hi_km]`` (lifetime increases monotonically with
    altitude, so the root is unique).

    Parameters
    ----------
    B : float
        Ballistic coefficient, kg/m^2.
    target_years : float
        Desired orbital lifetime, in years.
    k : float
        Solar-activity density multiplier (see :func:`lifetime_years`).
    lo_km, hi_km : float
        Altitude search bracket, in km.

    Returns
    -------
    float
        Altitude in km that yields ``target_years`` of lifetime.
    """

    def objective(h_km: float) -> float:
        return lifetime_years(h_km, B, k=k) - target_years

    return float(brentq(objective, lo_km, hi_km))
