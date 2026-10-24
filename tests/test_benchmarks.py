"""Validation and benchmark tests — maps to Design Blueprint Section 9.9.

This file is intended to be read on its own as the project's "here is our proof"
document. A mentor or juror should be able to open just this file and see the
credibility case for Ananke's numbers, without hunting through the per-module
test files (test_physics.py, test_deltav.py, test_reliability.py, etc.).

Each section below corresponds to one validation ID from the blueprint. Where a
check duplicates logic already covered elsewhere, it is re-asserted here with the
blueprint's exact reference numbers quoted in the docstring, so the provenance is
visible in one place.

+------+-------------------------------+-----------------------------------------------+-------------------------+
| ID   | What it checks                | Reference / expected                          | Pass criterion          |
+------+-------------------------------+-----------------------------------------------+-------------------------+
| V1   | Core physics formulas         | v(550)=7.585 km/s, T(550)=95.7 min;           | within 0.1% (speed,     |
|      | (orbit speed, period, dv)     | Hohmann LEO->GEO(300->35786)=3893 m/s         | period), within 1% (dv) |
| V5   | Reliability arithmetic        | required_reliability = 0.99 / (1 - p_coll);   | Exact (rel 1e-9)        |
|      |                               | round-trip p_pmd recovers 0.99                |                         |
| V6   | Rule-engine golden cases      | one just-PASS and one just-FAIL (and WARN     | 100% pass               |
|      | at each rule boundary         | where applicable) at each rule's threshold    |                         |
| V10  | No-solution case              | oversized/dense object, no feasible strategy  | Status INFEASIBLE,      |
|      |                               | in range                                      | never PASS              |
+------+-------------------------------+-----------------------------------------------+-------------------------+
"""

import pytest

from ananke.optimise.search import find_cheapest_designs
from ananke.physics.deltav import hohmann_dv_ms
from ananke.physics.lifetime import circular_speed_km_s, orbital_period_min
from ananke.physics.reliability import p_pmd, required_reliability
from ananke.rules.engine import evaluate_rule, load_catalogue
from ananke.schema import RuleStatus


# Load the real catalogue once and index rules by id, so the golden-case tests
# exercise the actual shipped rule definitions rather than hand-written copies
# (which could silently drift from catalogue.yaml).
_CATALOGUE = {rule["id"]: rule for rule in load_catalogue()}


def _rule(rule_id: str) -> dict:
    return _CATALOGUE[rule_id]


# --------------------------------------------------------------------------- #
# V1 — Formula unit tests
# --------------------------------------------------------------------------- #


class TestV1FormulaUnitTests:
    """V1: core physics formulas reproduce textbook reference values."""

    def test_circular_speed_and_period_at_550km(self):
        """Blueprint: v(550 km) = 7.585 km/s and T(550 km) = 95.7 min (within 0.1%)."""
        assert circular_speed_km_s(550) == pytest.approx(7.585, rel=0.001)
        assert orbital_period_min(550) == pytest.approx(95.7, rel=0.001)

    def test_hohmann_leo_to_geo(self):
        """Blueprint: textbook LEO->GEO Hohmann dv (300 -> 35786 km) = 3893 m/s (within 1%)."""
        assert hohmann_dv_ms(300, 35786) == pytest.approx(3893, rel=0.01)


# --------------------------------------------------------------------------- #
# V5 — Reliability arithmetic (blueprint: "Exact")
# --------------------------------------------------------------------------- #


class TestV5ReliabilityArithmetic:
    """V5: disposal-reliability arithmetic is exact (to floating-point tolerance).

    Note on p_collision = 0.02: required_reliability(0.02) = 0.99/0.98 = 1.0102,
    which exceeds 1.0. That is the intended "unachievable" signal — no real
    hardware reaches reliability >= 1 — so the round-trip identity is only
    meaningful for collision probabilities whose required reliability is <= 1.
    The unachievable case is asserted separately below (the tool must surface it,
    not fake a pass), which is the same "never a false PASS" principle as V10.
    """

    # All four cases exercise the raw arithmetic (does not call p_pmd).
    P_COLLISION_CASES = [0.001, 0.005, 0.01, 0.02]
    # Subset whose required reliability is physically achievable (<= 1.0), so the
    # p_pmd round-trip is well defined.
    ACHIEVABLE_P_COLLISION = [0.001, 0.005, 0.01]

    @pytest.mark.parametrize("p_coll", P_COLLISION_CASES)
    def test_required_reliability_is_exact(self, p_coll):
        """required_reliability(p) == 0.99 / (1 - p), exactly (rel 1e-9)."""
        assert required_reliability(p_coll) == pytest.approx(0.99 / (1 - p_coll), rel=1e-9)

    @pytest.mark.parametrize("p_coll", ACHIEVABLE_P_COLLISION)
    def test_round_trip_recovers_target(self, p_coll):
        """p_pmd(required_reliability(p), p) recovers the 0.99 target (rel 1e-9).

        Restricted to collision probabilities whose required reliability is <= 1
        (see class docstring); 0.02 is covered by the unachievable-case test.
        """
        r = required_reliability(p_coll)
        assert p_pmd(r, p_coll) == pytest.approx(0.99, rel=1e-9)

    def test_unachievable_reliability_is_flagged(self):
        """At p_collision = 0.02 the required reliability exceeds 1.0 (unachievable).

        The tool reports the raw value (> 1) rather than clamping it to a false
        pass; p_pmd then rejects an impossible reliability outright.
        """
        r = required_reliability(0.02)
        assert r > 1.0
        with pytest.raises(ValueError):
            p_pmd(r, 0.02)


# --------------------------------------------------------------------------- #
# V6 — Rule-engine golden cases (one just-PASS / just-FAIL at each boundary)
# --------------------------------------------------------------------------- #


class TestV6RuleEngineGoldenCases:
    """V6: each rule yields the right status right at its threshold.

    Metrics dicts are built directly here to isolate the rule-evaluation logic
    from compute_metrics. Rule definitions come from the real catalogue.yaml.
    """

    def test_r1_just_pass(self):
        """R1: worst-case lifetime just under 5 yr -> PASS."""
        result = evaluate_rule(
            _rule("R1"),
            {"lifetime_worst_after_disposal": 4.999, "lifetime_nominal_after_disposal": 4.999},
        )
        assert result.status == RuleStatus.PASS

    def test_r1_just_fail(self):
        """R1: both worst and nominal just over 5 yr -> FAIL."""
        result = evaluate_rule(
            _rule("R1"),
            {"lifetime_worst_after_disposal": 5.001, "lifetime_nominal_after_disposal": 5.001},
        )
        assert result.status == RuleStatus.FAIL

    def test_r1_warn_when_only_nominal_passes(self):
        """R1: worst just over 5 yr but nominal just under -> WARN."""
        result = evaluate_rule(
            _rule("R1"),
            {"lifetime_worst_after_disposal": 5.001, "lifetime_nominal_after_disposal": 4.999},
        )
        assert result.status == RuleStatus.WARN

    def test_r2_just_pass(self):
        """R2: p_pmd just above 0.99 -> PASS."""
        result = evaluate_rule(_rule("R2"), {"p_pmd": 0.9901})
        assert result.status == RuleStatus.PASS

    def test_r2_just_fail(self):
        """R2: p_pmd just below 0.99 -> FAIL (no warn_if, straight to FAIL)."""
        result = evaluate_rule(_rule("R2"), {"p_pmd": 0.9899})
        assert result.status == RuleStatus.FAIL

    def test_r3_just_pass(self):
        """R3: no human-band crossing -> PASS."""
        result = evaluate_rule(_rule("R3"), {"band_crossing_flag": 0.0})
        assert result.status == RuleStatus.PASS

    def test_r3_just_fail(self):
        """R3: human-band crossing present -> FAIL."""
        result = evaluate_rule(_rule("R3"), {"band_crossing_flag": 1.0})
        assert result.status == RuleStatus.FAIL

    def test_r5_just_pass(self):
        """R5: fuel margin just positive -> PASS."""
        result = evaluate_rule(_rule("R5"), {"fuel_margin_kg": 0.001})
        assert result.status == RuleStatus.PASS

    def test_r5_just_fail(self):
        """R5: fuel margin just negative -> FAIL."""
        result = evaluate_rule(_rule("R5"), {"fuel_margin_kg": -0.001})
        assert result.status == RuleStatus.FAIL

    def test_r9_just_pass(self):
        """R9: expected casualties just below 1e-4 -> PASS."""
        result = evaluate_rule(_rule("R9"), {"ec_total": 0.99e-4})
        assert result.status == RuleStatus.PASS

    def test_r9_just_fail(self):
        """R9: expected casualties just above 1e-4 -> FAIL."""
        result = evaluate_rule(_rule("R9"), {"ec_total": 1.01e-4})
        assert result.status == RuleStatus.FAIL


# --------------------------------------------------------------------------- #
# V10 — No-solution case (must report INFEASIBLE, never a false PASS)
# --------------------------------------------------------------------------- #


class TestV10NoSolutionCase:
    """V10: an oversized/dense object with no feasible strategy -> INFEASIBLE."""

    def test_oversized_dense_object_infeasible(self):
        """Very high ballistic coefficient, negligible fuel, no compliant altitude in range."""
        result = find_cheapest_designs(
            mass_kg=2000,
            cd=2.2,
            area_m2=0.5,
            isp_s=220,
            propellant_available_kg=0.01,
            desired_altitude_km=800,
            alt_min_km=700,
            alt_max_km=900,
        )
        assert result["status"] == "INFEASIBLE"
        assert result["candidates"] == []

    def test_second_no_solution_case_different_numbers(self):
        """A different oversized/dense case confirms this isn't a one-input fluke."""
        result = find_cheapest_designs(
            mass_kg=1500,
            cd=2.2,
            area_m2=0.4,
            isp_s=220,
            propellant_available_kg=0.005,
            desired_altitude_km=850,
            alt_min_km=750,
            alt_max_km=950,
        )
        assert result["status"] == "INFEASIBLE"
        assert result["candidates"] == []
