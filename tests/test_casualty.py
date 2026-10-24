"""Tests for Module C: re-entry casualty risk (Ec)."""

import math

import pytest

from ananke.physics.casualty import (
    debris_casualty_area,
    ec_uncontrolled,
    ec_with_failure,
)


def test_dca_single_component():
    """DCA of one 1 m^2 fragment is (0.6 + 1)^2 = 2.56 exactly."""
    assert debris_casualty_area([1.0]) == pytest.approx(2.56)


def test_dca_two_components():
    """DCA of two fragments is the sum of their individual danger patches."""
    expected = (0.6 + math.sqrt(1.0)) ** 2 + (0.6 + math.sqrt(2.0)) ** 2
    assert debris_casualty_area([1.0, 2.0]) == pytest.approx(expected)


def test_dca_empty_raises():
    """An empty component list is invalid."""
    with pytest.raises(ValueError):
        debris_casualty_area([])


def test_dca_negative_raises():
    """A negative area is invalid."""
    with pytest.raises(ValueError):
        debris_casualty_area([-1.0])


def test_ec_uncontrolled_nasa_reference():
    """NASA EUVE sanity check: DCA 12.41 m^2, rho 15/km^2 -> ~1/5300 (within 5%)."""
    assert ec_uncontrolled(12.41, 15.0) == pytest.approx(1.0 / 5300, rel=0.05)


def test_ec_with_failure_weighting():
    """Ec_total blends nominal and failure cases by p_fail."""
    expected = 0.9 * 1e-5 + 0.1 * 1e-3
    assert ec_with_failure(1e-5, 1e-3, 0.1) == pytest.approx(expected)


def test_ec_with_failure_rejects_bad_p_fail():
    """p_fail outside [0, 1] is invalid."""
    with pytest.raises(ValueError):
        ec_with_failure(1e-5, 1e-3, 1.5)
    with pytest.raises(ValueError):
        ec_with_failure(1e-5, 1e-3, -0.1)
