"""Tests for Module B: disposal delta-v and propellant budget."""

import pytest

from ananke.physics.deltav import (
    hohmann_dv_ms,
    perigee_lowering_dv_ms,
    propellant_fraction,
    propellant_mass_kg,
)


def test_hohmann_leo_to_geo():
    """LEO(300 km) -> GEO(35786 km) Hohmann Δv is ~3893 m/s (within 1%)."""
    assert hohmann_dv_ms(300, 35786) == pytest.approx(3893, rel=0.01)


def test_hohmann_order_independent():
    """Δv(750->500) equals Δv(500->750) in magnitude."""
    assert hohmann_dv_ms(750, 500) == pytest.approx(hohmann_dv_ms(500, 750), rel=1e-9)


def test_hohmann_disposal_worked_example():
    """Lowering 750 -> 504 km costs ~132 m/s (blueprint: roughly 130-135 m/s)."""
    dv = hohmann_dv_ms(750, 504)
    assert 130 <= dv <= 135, dv


def test_propellant_monoprop():
    """120 kg sat, 159 m/s Δv, Isp 220 s -> ~8.5 kg (~7% of mass)."""
    prop = propellant_mass_kg(120, 159, 220)
    assert 8.3 <= prop <= 8.7, prop


def test_propellant_cold_gas():
    """Same Δv with cold-gas Isp 60 s -> ~28 kg (~24% of mass)."""
    prop = propellant_mass_kg(120, 159, 60)
    assert 25 <= prop <= 31, prop


def test_propellant_increases_as_isp_decreases():
    """For fixed m0 and Δv, lower Isp needs more propellant."""
    props = [propellant_mass_kg(120, 159, isp) for isp in (300, 220, 100, 60)]
    assert props[0] < props[1] < props[2] < props[3], props


def test_propellant_fraction_consistency():
    """propellant_fraction equals propellant_mass / m0."""
    frac = propellant_fraction(120, 159, 220)
    mass = propellant_mass_kg(120, 159, 220)
    assert frac == pytest.approx(mass / 120, rel=1e-12)


def test_perigee_lowering_positive_and_smaller_than_hohmann():
    """A single perigee-lowering burn costs less than a full Hohmann transfer."""
    dv_perigee = perigee_lowering_dv_ms(750, 500)
    dv_hohmann = hohmann_dv_ms(750, 500)
    assert dv_perigee > 0
    assert dv_perigee < dv_hohmann
