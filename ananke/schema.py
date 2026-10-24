"""Pydantic data models for Ananke mission screening.

Defines the mission input schema (what a user describes about their satellite
and its disposal plan) and the screening output schema (lifetime estimate,
per-rule results, and suggestions).

Output fields are intentionally left as placeholders for now — they will be
populated as the physics, rules, and optimisation modules are built out.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class OrbitType(str, Enum):
    """Supported orbit geometries. Only circular is modelled for now."""

    circular = "circular"


class PropulsionType(str, Enum):
    """Onboard propulsion system class."""

    none = "none"
    cold_gas = "cold_gas"
    monoprop = "monoprop"
    biprop = "biprop"
    electric = "electric"


class DisposalStrategy(str, Enum):
    """End-of-life disposal approach."""

    natural_decay = "natural_decay"
    lower_to_circular = "lower_to_circular"
    lower_perigee = "lower_perigee"
    controlled_reentry = "controlled_reentry"


class RuleStatus(str, Enum):
    """Outcome of evaluating a single compliance rule."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NEEDS_INPUT = "NEEDS_INPUT"


# --------------------------------------------------------------------------- #
# Input sub-models
# --------------------------------------------------------------------------- #


class Orbit(BaseModel):
    """Orbital parameters of the mission."""

    type: OrbitType = Field(
        default=OrbitType.circular,
        description="Orbit geometry. Only 'circular' is supported for now.",
    )
    altitude_km: float = Field(
        ...,
        gt=0,
        description="Circular orbit altitude above Earth's surface (km).",
    )
    inclination_deg: float = Field(
        ...,
        ge=0,
        le=180,
        description="Orbital inclination (degrees).",
    )


class Propulsion(BaseModel):
    """Onboard propulsion capability used for disposal manoeuvres."""

    type: PropulsionType = Field(
        ...,
        description="Propulsion system class.",
    )
    isp_s: float = Field(
        ...,
        ge=0,
        description="Specific impulse (seconds).",
    )
    propellant_kg: float = Field(
        ...,
        ge=0,
        description="Propellant mass available for disposal (kg).",
    )
    reliability: float = Field(
        ...,
        ge=0,
        le=1,
        description="Probability the disposal manoeuvre succeeds (0-1).",
    )


class Disposal(BaseModel):
    """End-of-life disposal plan."""

    strategy: DisposalStrategy = Field(
        ...,
        description="Disposal strategy to be evaluated.",
    )
    target_alt_km: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Target altitude after the disposal manoeuvre (km), if applicable. "
            "0 denotes the surface (controlled re-entry)."
        ),
    )


class Checklist(BaseModel):
    """Qualitative compliance checklist items."""

    passivation: bool = Field(
        ...,
        description="Stored energy sources (batteries, tanks) will be passivated.",
    )
    trackable: bool = Field(
        ...,
        description="Object is trackable / will be registered for tracking.",
    )
    insurance: bool = Field(
        ...,
        description="Third-party liability insurance is in place.",
    )


class ReentryComponent(BaseModel):
    """A single spacecraft component expected to survive re-entry to the ground."""

    mass_kg: float = Field(..., gt=0, description="Component mass (kg).")
    area_m2: float = Field(
        ...,
        gt=0,
        description="Cross-section area of this surviving fragment (m^2).",
    )
    material: Optional[str] = Field(
        default=None,
        description="Component material (e.g. titanium, stainless steel).",
    )


class ReentryPlan(BaseModel):
    """Re-entry casualty inputs for a planned controlled re-entry."""

    components: list[ReentryComponent] = Field(
        ...,
        min_length=1,
        description="Surviving components; at least one is required.",
    )
    nominal_rho_eff_per_km2: float = Field(
        default=15.0,
        ge=0,
        description=(
            "Effective population density for the nominal landing footprint, "
            "people/km^2. Default 15.0 matches the published NASA EUVE reference case."
        ),
    )
    failure_rho_eff_per_km2: float = Field(
        default=15.0,
        ge=0,
        description=(
            "Effective population density assumed for the failure-case footprint, "
            "people/km^2."
        ),
    )
    p_fail: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description=(
            "Probability the controlled re-entry manoeuvre fails and follows an "
            "uncontrolled/off-nominal footprint instead."
        ),
    )
    target_lat: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
        description=(
            "Approximate target re-entry latitude (degrees), if known. "
            "Illustrative only — not used in the Ec/casualty calculation."
        ),
    )
    target_lon: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
        description=(
            "Approximate target re-entry longitude (degrees), if known. "
            "Illustrative only — not used in the Ec/casualty calculation."
        ),
    )


# --------------------------------------------------------------------------- #
# Mission input
# --------------------------------------------------------------------------- #


class MissionInput(BaseModel):
    """Full description of a satellite mission to be screened."""

    name: str = Field(..., description="Mission or spacecraft name.")
    mass_kg: float = Field(..., gt=0, description="Spacecraft mass (kg).")
    area_m2: float = Field(
        ...,
        gt=0,
        description="Mean cross-sectional area for drag (m^2).",
    )
    cd: float = Field(
        default=2.2,
        gt=0,
        description="Drag coefficient (dimensionless).",
    )
    orbit: Orbit = Field(..., description="Orbital parameters.")
    mission_life_yr: float = Field(
        ...,
        gt=0,
        description="Planned operational mission lifetime (years).",
    )
    propulsion: Propulsion = Field(..., description="Onboard propulsion capability.")
    p_collision: float = Field(
        ...,
        ge=0,
        le=1,
        description="Probability of a fatal collision during mission/disposal (0-1).",
    )
    disposal: Disposal = Field(..., description="End-of-life disposal plan.")
    checklist: Checklist = Field(..., description="Qualitative compliance checklist.")
    reentry: Optional[ReentryPlan] = Field(
        default=None,
        description=(
            "Re-entry casualty inputs. Required only if disposal.strategy is "
            "controlled_reentry; otherwise leave as None."
        ),
    )


# --------------------------------------------------------------------------- #
# Output sub-models
# --------------------------------------------------------------------------- #


class LifetimeEstimate(BaseModel):
    """Orbital lifetime estimate with an uncertainty band (years)."""

    best: float = Field(..., description="Best-case lifetime estimate (yr).")
    nominal: float = Field(..., description="Nominal lifetime estimate (yr).")
    worst: float = Field(..., description="Worst-case lifetime estimate (yr).")


class RuleResult(BaseModel):
    """Result of evaluating a single compliance rule."""

    id: str = Field(..., description="Rule identifier.")
    status: RuleStatus = Field(..., description="Evaluation outcome.")
    value: Optional[float] = Field(
        default=None,
        description="Computed value that was checked against the rule.",
    )
    limit: Optional[float] = Field(
        default=None,
        description="Regulatory limit the value is compared against.",
    )
    source: Optional[str] = Field(
        default=None,
        description="Citation / source of the rule.",
    )
    note: Optional[str] = Field(
        default=None,
        description="Human-readable explanation or context.",
    )


# --------------------------------------------------------------------------- #
# Mission output
# --------------------------------------------------------------------------- #


class MissionOutput(BaseModel):
    """Screening result for a mission. Populated as modules are built out."""

    lifetime_years: Optional[LifetimeEstimate] = Field(
        default=None,
        description="Orbital lifetime estimate (years).",
    )
    rules: list[RuleResult] = Field(
        default_factory=list,
        description="Per-rule compliance results.",
    )
    suggestions: list[dict] = Field(
        default_factory=list,
        description="Suggested design/operational changes (flexible structure for now).",
    )
    disclaimer: str = Field(
        default="Screening only. Not a regulatory submission.",
        description="Standard disclaimer shown with every result.",
    )
