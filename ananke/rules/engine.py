"""DFSM rule engine.

Loads the rule catalogue (catalogue.yaml), evaluates each rule against a
mission's computed metrics, and assembles a :class:`MissionOutput`. Each rule
compares a single metric against a limit and yields a PASS / FAIL / WARN /
NEEDS_INPUT status.

A rule may carry a ``warn_if`` clause: when the primary (typically worst-case)
limit fails but the ``warn_if`` (typically nominal-case) condition still holds,
the result is downgraded to WARN rather than a hard FAIL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ananke.rules.metrics import compute_metrics
from ananke.schema import (
    LifetimeEstimate,
    MissionInput,
    MissionOutput,
    RuleResult,
    RuleStatus,
)

_DEFAULT_CATALOGUE = Path(__file__).with_name("catalogue.yaml")


def load_catalogue(path: Optional[str] = None) -> list[dict]:
    """Load and parse the YAML rule catalogue.

    Parameters
    ----------
    path : str, optional
        Path to the catalogue file. Defaults to ``catalogue.yaml`` next to this
        module.

    Returns
    -------
    list[dict]
        The parsed list of rule definitions.
    """
    catalogue_path = Path(path) if path is not None else _DEFAULT_CATALOGUE
    with open(catalogue_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _compare(value: float, op: str, threshold: float) -> bool:
    """Apply a comparison operator between a value and a threshold.

    Supports "<", "<=", ">", ">=", "==".
    """
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "==":
        return value == threshold
    raise ValueError(f"Unsupported comparison operator: {op!r}")


def evaluate_rule(rule: dict, metrics: dict) -> RuleResult:
    """Evaluate a single catalogue rule against the computed metrics.

    Returns a :class:`RuleResult` with a PASS / FAIL / WARN / NEEDS_INPUT status.
    """
    source = f'{rule["source"]["doc"]}, {rule["source"]["clause"]}'
    limit_value = rule["limit"]["value"]
    value = metrics.get(rule["metric"])

    # Missing input: cannot evaluate.
    if value is None:
        return RuleResult(
            id=rule["id"],
            status=RuleStatus.NEEDS_INPUT,
            value=None,
            limit=limit_value,
            source=source,
            note="Required input missing — cannot evaluate this rule.",
        )

    passed = _compare(value, rule["limit"]["op"], limit_value)

    if passed:
        status = RuleStatus.PASS
        note = None
    elif "warn_if" in rule:
        warn = rule["warn_if"]
        warn_value = metrics.get(warn["metric"])
        if warn_value is not None and _compare(warn_value, warn["op"], warn["value"]):
            status = RuleStatus.WARN
            note = "Only the nominal case passes; worst-case does not."
        else:
            status = RuleStatus.FAIL
            note = None
    else:
        status = RuleStatus.FAIL
        note = None

    return RuleResult(
        id=rule["id"],
        status=status,
        value=value,
        limit=limit_value,
        source=source,
        note=note,
    )


def screen_mission(mission: MissionInput) -> MissionOutput:
    """Screen a mission against the DFSM rule catalogue.

    Computes metrics, evaluates every rule, and returns a populated
    :class:`MissionOutput`.
    """
    metrics = compute_metrics(mission)
    catalogue = load_catalogue()
    rules = [evaluate_rule(rule, metrics) for rule in catalogue]

    best = metrics["lifetime_best_after_disposal"]
    nominal = metrics["lifetime_nominal_after_disposal"]
    worst = metrics["lifetime_worst_after_disposal"]
    if None not in (best, nominal, worst):
        lifetime_years = LifetimeEstimate(best=best, nominal=nominal, worst=worst)
    else:
        lifetime_years = None

    return MissionOutput(
        lifetime_years=lifetime_years,
        rules=rules,
        suggestions=[],
    )
