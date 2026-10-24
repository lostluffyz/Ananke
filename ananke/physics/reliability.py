"""Post-mission disposal success probability (P_PMD).

ISRO's Debris-Free Space Mission (DFSM) guidance requires the post-mission
disposal success probability, P_PMD, to exceed 99%. Disposal only succeeds if
both of these hold:

    - the disposal hardware / manoeuvre actually works (reliability R_disposal), and
    - the satellite survives long enough to be disposed of, i.e. it is not
      destroyed by a collision first (probability 1 - P_collision).

Treating those as independent gives:

    P_PMD = R_disposal * (1 - P_collision)

We also invert this: for a known collision probability, what hardware
reliability R is needed to reach a target P_PMD?

    R = target / (1 - P_collision)

Caveat (from the design blueprint): no real disposal hardware achieves a
reliability of 1.0 (perfect). So if ``required_reliability`` returns a value
very close to, or above, 1.0, the active-disposal design is not credible for
that collision risk — the mission needs a fundamentally different approach
(for example, choosing a low enough orbit that natural decay handles disposal
without any manoeuvre). This module deliberately does NOT clamp such a result;
it returns the raw value (even if > 1) so the rule engine can flag it as
"cannot achieve" / "effectively impossible".
"""

from __future__ import annotations


def _check_unit_interval(name: str, value: float) -> None:
    """Raise ValueError if ``value`` is outside the closed interval [0, 1]."""
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")


def p_pmd(r_disposal: float, p_collision: float) -> float:
    """Post-mission disposal success probability.

    Computes ``R_disposal * (1 - P_collision)``.

    Parameters
    ----------
    r_disposal : float
        Reliability of the disposal hardware / manoeuvre succeeding, in [0, 1].
    p_collision : float
        Probability the satellite is destroyed by a collision before disposal,
        in [0, 1].

    Returns
    -------
    float
        P_PMD in [0, 1]. Compare against the 0.99 DFSM threshold.

    Raises
    ------
    ValueError
        If either input is outside [0, 1].
    """
    _check_unit_interval("r_disposal", r_disposal)
    _check_unit_interval("p_collision", p_collision)
    return r_disposal * (1.0 - p_collision)


def required_reliability(p_collision: float, target: float = 0.99) -> float:
    """Disposal reliability needed to reach a target P_PMD.

    Computes ``target / (1 - P_collision)`` — the minimum hardware reliability
    R_disposal that, combined with the given collision risk, reaches ``target``.

    The result is returned raw and is NOT clamped to 1.0. A value at or above
    1.0 means no achievable hardware reliability can meet the target for this
    collision risk (real hardware never reaches R = 1.0), which signals the
    design should switch to a fundamentally different disposal approach such as
    natural decay. The rule engine (built later) is responsible for flagging
    that condition.

    Parameters
    ----------
    p_collision : float
        Probability of collision before disposal, in [0, 1). Must be strictly
        less than 1 (P_collision = 1 means certain destruction, which would
        divide by zero).
    target : float
        Target P_PMD to achieve (default 0.99, the DFSM threshold).

    Returns
    -------
    float
        Required reliability. May exceed 1.0 (see above).

    Raises
    ------
    ValueError
        If ``p_collision`` is not in [0, 1) (i.e. negative or >= 1).
    """
    if not (0.0 <= p_collision < 1.0):
        raise ValueError(
            f"p_collision must be in [0, 1) (strictly less than 1), got {p_collision!r}"
        )
    return target / (1.0 - p_collision)
