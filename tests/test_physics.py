"""Tests for Module A: orbital lifetime due to atmospheric drag."""

import pytest

from ananke.physics.lifetime import (
    altitude_for_lifetime,
    ballistic_coefficient,
    circular_speed_km_s,
    lifetime_range,
    lifetime_years,
    orbital_period_min,
)


def test_circular_speed_550km():
    """Circular speed at 550 km is ~7.585 km/s (within 0.5%)."""
    assert circular_speed_km_s(550) == pytest.approx(7.585, rel=0.005)


def test_orbital_period_550km():
    """Orbital period at 550 km is ~95.7 minutes (within 0.5%)."""
    assert orbital_period_min(550) == pytest.approx(95.7, rel=0.005)


def test_ballistic_coefficient():
    """B for mass=120 kg, Cd=2.2, A=1.2 m^2 is ~45.45 kg/m^2 (within 1%)."""
    assert ballistic_coefficient(120, 2.2, 1.2) == pytest.approx(45.45, rel=0.01)


def test_lifetime_worked_example_order_of_magnitude():
    """At 750 km with B=45.45, nominal lifetime is roughly 80-130 years."""
    B = ballistic_coefficient(120, 2.2, 1.2)
    band = lifetime_range(750, B)
    assert 80 <= band["nominal"] <= 130, band


def test_lifetime_band_ordering_and_scaling():
    """best < nominal < worst, and lifetime scales roughly inversely with k."""
    B = ballistic_coefficient(120, 2.2, 1.2)
    band = lifetime_range(750, B)

    assert band["best"] < band["nominal"] < band["worst"], band

    # Drag scales linearly with k, so lifetime scales ~ 1/k.
    # best uses k=2.0 -> ~0.5x nominal; worst uses k=0.5 -> ~2x nominal.
    assert band["best"] / band["nominal"] == pytest.approx(0.5, rel=0.25), band
    assert band["worst"] / band["nominal"] == pytest.approx(2.0, rel=0.25), band


def test_altitude_for_lifetime_worst_case():
    """Altitude giving 5-year worst-case (k=0.5) lifetime is ~504 km (450-560)."""
    B = ballistic_coefficient(120, 2.2, 1.2)
    alt = altitude_for_lifetime(B, target_years=5.0, k=0.5)
    assert 450 <= alt <= 560, alt


def test_lifetime_monotonic_in_altitude():
    """Lifetime strictly increases with altitude (400 < 600 < 800 km)."""
    B = ballistic_coefficient(120, 2.2, 1.2)
    life_400 = lifetime_years(400, B)
    life_600 = lifetime_years(600, B)
    life_800 = lifetime_years(800, B)
    assert life_400 < life_600 < life_800, (life_400, life_600, life_800)
