"""Draft Space Debris Mitigation Plan dossier (PDF).

Renders a mission screening into a plain, readable PDF using reportlab. The
document is explicitly a DRAFT for design-stage screening — not a regulatory
submission. Styling is intentionally minimal (no custom fonts or logos);
branding arrives with the later UI/styling pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ananke.schema import MissionInput, MissionOutput

_DISCLAIMER_APPENDIX = (
    "This is an automatically generated draft for design-stage screening. It is "
    "not a submission to ISRO or IN-SPACe and does not constitute regulatory "
    "approval."
)

_FINAL_DISCLAIMER = (
    "Screening only. Not a regulatory submission. Ananke is a design-stage "
    "planning aid; only ISRO and IN-SPACe can determine actual regulatory "
    "compliance."
)

_METHODS_TEXT_PHYSICS = (
    "The physics used here — orbital decay, Hohmann transfer, and the rocket "
    "equation — are simplified textbook models (a piecewise-exponential "
    "atmosphere and a circular-orbit approximation), intended for early design "
    "screening rather than high-fidelity analysis. Each rule's source document "
    "and clause are shown in the compliance table above. This tool has not yet "
    "been benchmarked against NASA DAS or ESA DRAMA, so its numbers should be "
    "treated as indicative, not validated."
)

_ML_SENTENCE_GENERIC = (
    "A machine-learning surrogate is also available in the app for fast "
    "orbital-lifetime previews; it is trained on physics-simulated data with "
    "reported hold-out accuracy and is never used for the compliance "
    "determination shown in this dossier."
)


def _ml_methods_sentence(ml_metrics: Optional[dict]) -> str:
    """Methods-section sentence about the ML surrogate.

    When real hold-out metrics are supplied, report BOTH R^2 values (log-space,
    which the model is trained against, and the lower tail-dominated year-space
    figure) plus the median proportional error — so the dossier never shows only
    the flattering number. Falls back to a generic sentence when metrics are not
    passed (older callers), keeping the section valid.
    """
    if not ml_metrics:
        return _ML_SENTENCE_GENERIC
    return (
        "A machine-learning surrogate is also available in the app for fast "
        "orbital-lifetime previews. It is a random forest trained on "
        f"{ml_metrics['n_train']} physics-simulated missions and validated on "
        f"{ml_metrics['n_holdout']} held out: log-space R² = "
        f"{ml_metrics['r2_log_space']:.3f} (the metric it is trained against), "
        f"while year-space R² = {ml_metrics['r2']:.3f} is lower because a few "
        "extreme-lifetime outliers dominate raw variance — median error on "
        f"realistic missions is {ml_metrics['median_ape_pct']:.1f}%. It is never "
        "used for the compliance determination shown in this dossier."
    )


def _fmt(value, suffix: str = "") -> str:
    """Format a value for a table cell, rendering None as 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value}{suffix}"


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def _mission_summary_rows(mission: MissionInput) -> list[list[str]]:
    """Human-readable (label, value) rows for the mission summary table."""
    disposal = mission.disposal
    prop = mission.propulsion
    orbit = mission.orbit
    checklist = mission.checklist
    return [
        ["Field", "Value"],
        ["Name", mission.name],
        ["Mass (kg)", _fmt(mission.mass_kg)],
        ["Area (m²)", _fmt(mission.area_m2)],
        ["Cd", _fmt(mission.cd)],
        ["Orbit altitude (km)", _fmt(orbit.altitude_km)],
        ["Inclination (deg)", _fmt(orbit.inclination_deg)],
        ["Mission life (yr)", _fmt(mission.mission_life_yr)],
        ["Propulsion type", prop.type.value],
        ["Isp (s)", _fmt(prop.isp_s)],
        ["Propellant available (kg)", _fmt(prop.propellant_kg)],
        ["Disposal reliability", _fmt(prop.reliability)],
        ["Collision probability", _fmt(mission.p_collision)],
        ["Disposal strategy", disposal.strategy.value],
        ["Target altitude (km)", _fmt(disposal.target_alt_km)],
        ["Passivation", _yes_no(checklist.passivation)],
        ["Trackable", _yes_no(checklist.trackable)],
        ["Insurance", _yes_no(checklist.insurance)],
    ]


def _grid_style(header: bool = True) -> TableStyle:
    """Standard thin-grid table style, optionally with a shaded header row."""
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    return TableStyle(commands)


def generate_dossier_pdf(
    mission: MissionInput,
    output: MissionOutput,
    optimiser_result: Optional[dict] = None,
    ml_metrics: Optional[dict] = None,
    output_path: str = "ananke_dossier.pdf",
) -> str:
    """Render a mission screening to a draft PDF dossier.

    Parameters
    ----------
    mission : MissionInput
        The screened mission.
    output : MissionOutput
        Screening results (lifetime, rules, disclaimer).
    optimiser_result : dict, optional
        Result from the cheapest-design optimiser. When provided, a "Suggested
        Design Changes" section is included.
    ml_metrics : dict, optional
        Hold-out metrics from :func:`ananke.ml.surrogate.train_surrogate`. When
        provided, the Methods section reports the surrogate's real accuracy
        (both R^2 values and median proportional error); otherwise a generic
        sentence is used.
    output_path : str
        Where to write the PDF.

    Returns
    -------
    str
        ``output_path``, so the caller knows where the file landed.
    """
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    title_style = styles["Title"]

    bold_body = styles["BodyText"].clone("BoldBody")
    bold_body.fontName = "Helvetica-Bold"

    story = []

    # (a) Title block.
    today = datetime.now().strftime("%d %B %Y")
    story.append(Paragraph("Ananke &mdash; Draft Space Debris Mitigation Plan", title_style))
    story.append(Paragraph(f"Mission: {mission.name}", h2))
    story.append(Paragraph(f"Generated: {today}", body))
    story.append(Spacer(1, 6 * mm))

    # (b) Disclaimer box near the top.
    disclaimer_text = f"{output.disclaimer} {_DISCLAIMER_APPENDIX}"
    disclaimer_para = Paragraph(disclaimer_text, bold_body)
    disclaimer_box = Table([[disclaimer_para]], colWidths=[170 * mm])
    disclaimer_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(disclaimer_box)
    story.append(Spacer(1, 6 * mm))

    # (c) Mission summary.
    story.append(Paragraph("1. Mission Summary", h1))
    summary = Table(_mission_summary_rows(mission), colWidths=[70 * mm, 100 * mm])
    summary.setStyle(_grid_style(header=True))
    story.append(summary)
    story.append(Spacer(1, 6 * mm))

    # (d) Orbital lifetime estimate.
    story.append(Paragraph("2. Orbital Lifetime Estimate", h1))
    if output.lifetime_years is not None:
        lt = output.lifetime_years
        lifetime_rows = [
            ["Best (yr)", "Nominal (yr)", "Worst (yr)"],
            [f"{lt.best:.1f}", f"{lt.nominal:.1f}", f"{lt.worst:.1f}"],
        ]
        lifetime_table = Table(lifetime_rows, colWidths=[56 * mm, 57 * mm, 57 * mm])
        lifetime_table.setStyle(_grid_style(header=True))
        story.append(lifetime_table)
    else:
        story.append(Paragraph("Not available &mdash; required input missing.", body))
    story.append(Spacer(1, 6 * mm))

    # (e) Rule-by-rule compliance results.
    story.append(Paragraph("3. Rule-by-Rule Compliance Results", h1))
    total = len(output.rules)
    n_pass = sum(1 for r in output.rules if r.status.value == "PASS")
    story.append(Paragraph(f"Readiness: {n_pass} of {total} rules PASS", bold_body))
    story.append(Spacer(1, 2 * mm))

    rule_rows = [["Rule ID", "Status", "Value", "Limit", "Source", "Note"]]
    for r in output.rules:
        value_str = "N/A" if r.value is None else f"{r.value:.4g}"
        limit_str = "N/A" if r.limit is None else f"{r.limit:.4g}"
        rule_rows.append(
            [
                r.id,
                r.status.value,
                value_str,
                limit_str,
                Paragraph(r.source or "", body),
                Paragraph(r.note or "", body),
            ]
        )
    rule_table = Table(
        rule_rows,
        colWidths=[16 * mm, 22 * mm, 20 * mm, 20 * mm, 46 * mm, 46 * mm],
        repeatRows=1,
    )
    rule_table.setStyle(_grid_style(header=True))
    story.append(rule_table)
    story.append(Spacer(1, 6 * mm))

    # (f) Suggested design changes (only if an optimiser result was provided).
    if optimiser_result is not None:
        story.append(Paragraph("4. Suggested Design Changes", h1))
        # Search-effort line (uses the real evaluated count). .get() with a None
        # guard keeps older optimiser results (without the key) working.
        n_evaluated = optimiser_result.get("total_candidates_evaluated")
        if n_evaluated is not None:
            story.append(
                Paragraph(
                    f"Searched {n_evaluated} altitude/disposal-strategy combinations "
                    "under worst-case solar assumptions to find the cheapest "
                    "compliant design.",
                    body,
                )
            )
            story.append(Spacer(1, 2 * mm))
        if optimiser_result.get("status") == "OK":
            for cand in optimiser_result.get("candidates", []):
                bullet = (
                    f"&bull; Altitude {cand['altitude_km']:.0f} km &mdash; "
                    f"{cand['strategy']} &mdash; "
                    f"propellant needed {cand['propellant_kg']:.2f} kg"
                )
                story.append(Paragraph(bullet, body))
        else:
            message = optimiser_result.get("message", "No feasible design found.")
            story.append(Paragraph(message, bold_body))
        story.append(Spacer(1, 6 * mm))

    # (g) Methods and sources.
    story.append(Paragraph("5. Methods and Sources", h1))
    methods_text = f"{_METHODS_TEXT_PHYSICS} {_ml_methods_sentence(ml_metrics)}"
    story.append(Paragraph(methods_text, body))
    story.append(Spacer(1, 6 * mm))

    # (h) Final disclaimer.
    story.append(Paragraph("6. Disclaimer", h1))
    story.append(Paragraph(_FINAL_DISCLAIMER, bold_body))

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        title="Ananke Draft Space Debris Mitigation Plan",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story)
    return output_path
