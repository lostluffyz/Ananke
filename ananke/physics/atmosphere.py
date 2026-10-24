"""Piecewise-exponential atmospheric density model.

Used by the orbital-lifetime integration to look up air density as a function
of altitude. The model is the standard textbook piecewise-exponential fit:

    rho(h) = k * rho0 * exp(-(h - h0) / H)

where (h0, rho0, H) is the table row with the largest base altitude h0 that is
still <= h. Units: h and H in km, rho0 in kg/m^3, so rho is returned in kg/m^3.

The multiplier ``k`` is a coarse stand-in for solar-activity uncertainty, which
swells or thins the upper atmosphere:

    k = 1.0  -> nominal atmosphere.
    k = 2.0  -> high solar activity: denser air, faster decay. This is the
                "best case" for meeting a 25-year / 5-year disposal rule, since
                the satellite comes down sooner.
    k = 0.5  -> low solar activity: thinner air, slower decay. This is the
                "worst case" for a disposal rule, since the satellite lingers.
"""

from __future__ import annotations

import numpy as np

# Standard piecewise-exponential atmosphere table.
# Each row: [base altitude h0 (km), reference density rho0 (kg/m^3), scale height H (km)].
ATM_TABLE = [
    [0, 1.225, 7.249],
    [25, 3.899e-2, 6.349],
    [30, 1.774e-2, 6.682],
    [40, 3.972e-3, 7.554],
    [50, 1.057e-3, 8.382],
    [60, 3.206e-4, 7.714],
    [70, 8.770e-5, 6.549],
    [80, 1.905e-5, 5.799],
    [90, 3.396e-6, 5.382],
    [100, 5.297e-7, 5.877],
    [110, 9.661e-8, 7.263],
    [120, 2.438e-8, 9.473],
    [130, 8.484e-9, 12.636],
    [140, 3.845e-9, 16.149],
    [150, 2.070e-9, 22.523],
    [180, 5.464e-10, 29.740],
    [200, 2.789e-10, 37.105],
    [250, 7.248e-11, 45.546],
    [300, 2.418e-11, 53.628],
    [350, 9.518e-12, 53.298],
    [400, 3.725e-12, 58.515],
    [450, 1.585e-12, 60.828],
    [500, 6.967e-13, 63.822],
    [600, 1.454e-13, 71.835],
    [700, 3.614e-14, 88.667],
    [800, 1.170e-14, 124.64],
    [900, 5.245e-15, 181.05],
    [1000, 3.019e-15, 268.00],
]

# Pre-split columns as numpy arrays for fast, array-safe lookups.
_ATM = np.asarray(ATM_TABLE, dtype=float)
_H0 = _ATM[:, 0]
_RHO0 = _ATM[:, 1]
_SH = _ATM[:, 2]


def rho(h_km: float, k: float = 1.0) -> float:
    """Atmospheric density at altitude ``h_km`` (km), in kg/m^3.

    Selects the table row with the largest base altitude <= ``h_km`` and applies
    the exponential falloff ``k * rho0 * exp(-(h - h0) / H)``. Accepts a scalar
    or a numpy array of altitudes; returns the same shape.

    Parameters
    ----------
    h_km : float
        Altitude above Earth's surface, in km.
    k : float
        Solar-activity density multiplier (1.0 nominal, 2.0 high, 0.5 low).

    Returns
    -------
    float
        Density in kg/m^3 (a numpy array if ``h_km`` is array-valued).
    """
    h = np.asarray(h_km, dtype=float)
    # Largest h0 <= h: searchsorted(side="right") gives insertion index, -1 for the row below.
    idx = np.searchsorted(_H0, h, side="right") - 1
    idx = np.clip(idx, 0, len(_H0) - 1)

    h0 = _H0[idx]
    rho0 = _RHO0[idx]
    scale_h = _SH[idx]
    result = k * rho0 * np.exp(-(h - h0) / scale_h)

    if np.ndim(h_km) == 0:
        return float(result)
    return result
