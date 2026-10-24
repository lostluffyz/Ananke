"""Tests for Module D: disposal success probability (P_PMD)."""

import pytest

from ananke.physics.reliability import p_pmd, required_reliability


def test_p_pmd_warn_example():
    """R=0.995, P_coll=0.002 -> P_PMD ~0.993 (thin margin above 0.99)."""
    assert p_pmd(0.995, 0.002) == pytest.approx(0.993, rel=0.001)


def test_required_reliability_low_collision():
    """P_collision = 0.1% -> R >= ~0.991."""
    assert required_reliability(0.001) == pytest.approx(0.991, rel=0.001)


def test_required_reliability_mid_collision():
    """P_collision = 0.5% -> R >= ~0.995."""
    assert required_reliability(0.005) == pytest.approx(0.995, rel=0.001)


def test_required_reliability_high_collision():
    """P_collision = 1% -> R ~= 1.000 (effectively perfect reliability)."""
    assert required_reliability(0.01) == pytest.approx(1.000, rel=0.001)


def test_p_pmd_rejects_out_of_range():
    """p_pmd raises ValueError for inputs outside [0, 1]."""
    with pytest.raises(ValueError):
        p_pmd(-0.1, 0.002)
    with pytest.raises(ValueError):
        p_pmd(0.995, 1.5)


def test_required_reliability_rejects_certain_collision():
    """required_reliability raises ValueError when p_collision >= 1."""
    with pytest.raises(ValueError):
        required_reliability(1.0)
    with pytest.raises(ValueError):
        required_reliability(1.2)


def test_round_trip_recovers_target():
    """R = required_reliability(p_coll); p_pmd(R, p_coll) ~= target."""
    p_coll = 0.003
    r = required_reliability(p_coll)  # default target 0.99
    assert p_pmd(r, p_coll) == pytest.approx(0.99, rel=1e-12)
