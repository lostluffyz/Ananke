"""Ananke MVP — Streamlit app with Ananke brand identity.

Visual/structural pass: applies the Ananke brand kit (navy text, warm Jupiter
Tan/Band accents, logos) over the existing form/screening/optimiser/PDF logic.
Navigation is a floating pill bar at the top of the page using
st.segmented_control (Streamlit 1.36+): a compact Ananke submark sits to its
left, the three sections (Mission Setup / Results / Dossier) are the segments.
A footer below all content holds the Roadmap Stage-2 items and the Tracr
Aerospace credit.  The main pane renders one section at a time, chosen by
st.session_state["nav"].
No functional logic changed here — only presentation and layout.
"""

import html as _html
import os
import tempfile
import textwrap
import time
from pathlib import Path
from string import Template
from typing import Optional

import pandas as pd
import pydeck as pdk
import streamlit as st

from ananke.ml.surrogate import (
    generate_training_data,
    predict_lifetime_years,
    train_surrogate,
)
from ananke.optimise.search import find_cheapest_designs, propellant_vs_altitude
from ananke.physics.lifetime import ballistic_coefficient, lifetime_years
from ananke.report.dossier import generate_dossier_pdf
from ananke.rules.engine import load_catalogue, screen_mission
from ananke.schema import DisposalStrategy, MissionInput, PropulsionType

# Page config must be the first Streamlit command in the script.
st.set_page_config(
    page_title="Ananke",
    page_icon="assets/Ananke_FL.png",
    layout="wide",
)

# One-time animated splash screen shown only on first load per browser session.
st.session_state.setdefault("splash_shown", False)

if not st.session_state["splash_shown"]:
    splash_file = Path("assets/ananke_splash.svg")
    if splash_file.exists():
        raw_svg = splash_file.read_text(encoding="utf-8")
        # In Markdown, lines indented with 4+ spaces after empty lines are parsed
        # as <pre><code> blocks. Stripping line indentation and blank lines ensures
        # Streamlit's markdown-it renderer treats the full SVG as raw HTML.
        clean_svg = "\n".join(line.strip() for line in raw_svg.splitlines() if line.strip())

        splash_placeholder = st.empty()
        splash_html = (
            "<style>\n"
            "@media (prefers-reduced-motion: reduce) {\n"
            "  #ananke-splash-overlay * {\n"
            "    animation-duration: 0.01ms !important;\n"
            "    animation-iteration-count: 1 !important;\n"
            "    transition-duration: 0.01ms !important;\n"
            "  }\n"
            "}\n"
            "</style>\n"
            '<div id="ananke-splash-overlay" style="'
            "position: fixed; inset: 0; z-index: 9999; "
            "background: #FEFEFE; "
            "display: flex; align-items: center; justify-content: center;"
            '">\n'
            '<div style="width: min(340px, 60vw); height: min(340px, 60vw);">\n'
            f"{clean_svg}\n"
            "</div>\n"
            "</div>"
        )
        splash_placeholder.markdown(splash_html, unsafe_allow_html=True)
        # Reduced-motion handling:
        # Streamlit executes server-side Python and does not provide a native API to inspect the
        # browser's window.matchMedia('(prefers-reduced-motion: reduce)') without an asynchronous
        # roundtrip. A future enhancement could inject a lightweight JS snippet writing client
        # preference to st.query_params or session_state on first paint.
        # Pragmatic check: inspect query params or session state for reduced_motion preference.
        # If enabled, cut the display hold to ~0.6s total; otherwise wait the full 2.60s animation
        # duration (determined by .typography-silk and .silk-shimmer-wave) plus a ~0.3s hold = 2.90s.
        is_reduced_motion = (
            st.session_state.get("reduced_motion", False)
            or st.query_params.get("reduced_motion", "").lower() in ("1", "true", "yes")
        )
        hold_time = 0.6 if is_reduced_motion else 2.90
        time.sleep(hold_time)
        splash_placeholder.empty()
    st.session_state["splash_shown"] = True

# Active section for the navigation. Set before any rendering so
# the CSS below can highlight the current nav segment. Defaults to "setup".
st.session_state.setdefault("nav", "setup")
nav = st.session_state["nav"]

PROPULSION_OPTIONS = [p.value for p in PropulsionType]
DISPOSAL_OPTIONS = [d.value for d in DisposalStrategy]

# Brand palette.
ANANKE_NAVY = "#0C1520"
JUPITER_TAN = "#BDA48A"
JUPITER_BAND = "#9F7B59"
JUPITER_BAND_DARK = "#7F6144"  # slightly darker for button hover
TRACR_INDIGO = "#4A48FB"

# Readiness headline text colors (green all-pass / amber partial / red safety-fail).
READINESS_GREEN = "#1E8E3E"
READINESS_AMBER = "#B8860B"
READINESS_RED = "#C62828"

RULE_DETAIL = {
    "R1": {
        "requirement": "Post-mission orbital lifetime must be under 5 years "
            "after disposal, or the mission must use controlled re-entry.",
        "inputs": "mass, cross-section area, drag coefficient (→ ballistic "
            "coefficient), post-disposal altitude",
        "method": "Atmospheric-drag orbital decay, integrated from the "
            "post-disposal altitude using a static exponential atmosphere "
            "model, evaluated at the worst-case (low solar activity, "
            "slower decay) density multiplier.",
        "limit_direction": "upper",  # value must be BELOW limit to pass
    },
    "R2": {
        "requirement": "Post-mission disposal success probability (P_PMD) "
            "must exceed 99%.",
        "inputs": "disposal hardware reliability, collision probability",
        "method": "P_PMD = reliability × (1 − collision probability).",
        "limit_direction": "lower",  # value must be ABOVE limit to pass
    },
    "R3": {
        "requirement": "The mission must avoid transfers or disposal within "
            "the 370–430 km human-spaceflight protected band.",
        "inputs": "operational altitude, post-disposal altitude",
        "method": "Checks whether either the operational altitude or the "
            "post-disposal altitude falls inside the 370–430 km band.",
        "limit_direction": "boolean",  # 0 = no crossing (pass), 1 = crossing (fail)
    },
    "R5": {
        "requirement": "Propellant must be budgeted for the disposal burn, "
            "with margin.",
        "inputs": "spacecraft mass, engine Isp, propellant carried, "
            "disposal target altitude",
        "method": "Required propellant is computed via the rocket equation "
            "from the Hohmann-transfer delta-v to the disposal altitude "
            "(with a 20% margin), then compared against propellant "
            "actually carried.",
        "limit_direction": "lower",
    },
    "R9": {
        "requirement": "Expected casualties from a planned re-entry must be "
            "below 1 in 10,000.",
        "inputs": "surviving-fragment areas, effective population density "
            "(nominal and failure-case), manoeuvre failure probability",
        "method": "Debris casualty area from surviving fragments is "
            "converted to expected casualties via effective population "
            "density, blended between the nominal and failure-case "
            "footprints by the manoeuvre's failure probability. Only "
            "computed when disposal strategy is controlled re-entry.",
        "limit_direction": "upper",
    },
}

RULE_UNITS = {
    "R1": "yr",
    "R2": "",
    "R5": "kg",
    "R9": "",
}

RULE_TITLES = {r["id"]: r.get("title", "") for r in load_catalogue()}

# --------------------------------------------------------------------------- #
# Design tokens — single source of truth (§1.2).
# --------------------------------------------------------------------------- #

TOKENS = {
    # Brand (unchanged)
    "navy": "#0C1520", "white": "#FEFEFE", "earth": "#E1E1E0",
    "tan": "#BDA48A", "band": "#9F7B59", "band_dark": "#7F6144",
    "tracr": "#4A48FB",                      # Tracr credit text ONLY

    # Derived neutrals
    "surface": "#F6F6F4", "surface_2": "#EEEDEA",
    "border_strong": "#C8C7C3", "muted": "#4E5A67",

    # Derived accent
    "band_hover": "#6B5138", "band_wash": "#F3EDE6",

    # Status: text / background / line
    "pass": "#17694C", "pass_bg": "#E8F3EE", "pass_line": "#B7D9C8",
    "fail": "#A1231C", "fail_bg": "#FBEAE9", "fail_line": "#EDBDB9",
    "warn": "#9A5300", "warn_bg": "#FBF0DD", "warn_line": "#E8C98F",
    "need": "#465A6E", "need_bg": "#EAEFF3", "need_line": "#C3CFDA",

    # Type
    "font": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "mono": 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',

    # Spacing (4 px base) and radius
    "s1": "4px", "s2": "8px", "s3": "12px", "s4": "16px", "s5": "24px", "s6": "32px", "s7": "48px",
    "r_chip": "4px", "r_ctl": "6px", "r_card": "8px",
}


def root_css(t: dict = TOKENS) -> str:
    """Render tokens as CSS custom properties (kebab-case, an- prefix)."""
    lines = [f"--an-{k.replace('_', '-')}: {v};" for k, v in t.items()]
    return ":root{" + "".join(lines) + "}"


# --------------------------------------------------------------------------- #
# Helper functions (§1.5, §2.4, §2.5).
# --------------------------------------------------------------------------- #

def esc(x) -> str:
    """HTML-escape a dynamic value for safe injection."""
    return _html.escape(str(x), quote=True)


STATUS_LABEL = {
    "PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN",
    "NEEDS_INPUT": "NEEDS INPUT", "INFEASIBLE": "INFEASIBLE",
    "pass": "PASS", "fail": "FAIL", "warn": "WARN",
    "needs_input": "NEEDS INPUT", "infeasible": "INFEASIBLE",
}


def skey(status: str) -> str:
    """Convert status enum value to a CSS-safe key: 'NEEDS_INPUT' -> 'needs-input'."""
    return status.lower().replace("_", "-")


TAGS = {
    "physics":   ("Physics",    "Deterministic physics model. Supplies the numbers the rules use."),
    "rules":     ("Rules",      "Deterministic rule check against the cited limit. Sets PASS / FAIL / WARN / NEEDS INPUT."),
    "optimiser": ("Optimiser",  "Classical search and constrained optimisation. Not machine learning."),
    "ml":        ("ML preview", "Trained surrogate for fast lifetime previews. Never used for PASS / FAIL."),
}


def tag(kind: str) -> str:
    """Render a provenance tag (Physics / Rules / Optimiser / ML preview)."""
    text, tip = TAGS[kind]
    return f'<span class="an-tag an-tag--{kind}" title="{esc(tip)}">{esc(text)}</span>'


def chip(status: str) -> str:
    """Render a status chip (PASS / FAIL / WARN / NEEDS INPUT / INFEASIBLE)."""
    return f'<span class="an-chip an-chip--{skey(status)}">{STATUS_LABEL[status]}</span>'


def metric_card(label, value, unit="", *, status=None, sub=None, basis=None, tag_kind=None) -> str:
    """Build the value / unit / label HTML pattern for a single metric."""
    p = [
        f'<div class="an-metric" data-status="{skey(status) if status else "none"}">',
        '<div class="an-metric__head">',
        f'<span class="an-metric__label">{esc(label)}</span>',
        chip(status) if status else "",
        '</div>',
        '<div class="an-metric__row">',
        f'<span class="an-metric__value an-num">{esc(value)}</span>',
        f'<span class="an-metric__unit">{esc(unit)}</span>' if unit else "",
        '</div>',
    ]
    if sub:
        p.append(f'<div class="an-metric__sub an-num">{esc(sub)}</div>')
    if basis:
        p.append(f'<div class="an-metric__basis">{tag(tag_kind) if tag_kind else ""}{esc(basis)}</div>')
    p.append('</div>')
    return "".join(p)


def kv_block(pairs) -> str:
    """Render a key/value definition list from [(label, value), ...]."""
    return '<dl class="an-kv">' + "".join(
        f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in pairs) + '</dl>'


def note(kind: str, text: str) -> str:
    """Render a notice block. kind: 'info' | 'warn' | 'fail'."""
    return f'<div class="an-note an-note--{kind}">{esc(text)}</div>'


def compute_rule_margin(rule_id: str, value: Optional[float], limit: Optional[float], limit_dir: str) -> Optional[str]:
    """Calculate and format rule margin with correct sign and true minus sign (U+2212)."""
    if value is None or limit is None or limit_dir == "boolean":
        return None

    if limit_dir == "upper":
        margin = limit - value
    elif limit_dir == "lower":
        margin = value - limit
    else:
        return None

    unit = RULE_UNITS.get(rule_id, "")
    unit_str = f" {unit}" if unit else ""
    prec = 3 if (rule_id == "R2" or (0 < abs(margin) < 0.01)) else 2

    if margin >= 0:
        return f"+{margin:.{prec}f}{unit_str} headroom"
    else:
        mag = abs(margin)
        return f"\u2212{mag:.{prec}f}{unit_str} (exceeds limit by {mag:.{prec}f}{unit_str})"


def format_rule_label_values(rule):
    """Format computed value and limit strings for expander headers."""
    rid = rule.id
    if rid == "R1":
        v_str = f"{rule.value:.1f} yr" if rule.value is not None else "Not computed"
        l_str = f"< {rule.limit:.1f} yr" if rule.limit is not None else "—"
    elif rid == "R2":
        v_str = f"{rule.value:.3f}" if rule.value is not None else "Not computed"
        l_str = f"> {rule.limit:.2f}" if rule.limit is not None else "—"
    elif rid == "R3":
        v_str = "No crossing" if rule.value == 0.0 else ("Crosses the protected band" if rule.value == 1.0 else "Not computed")
        l_str = "No crossing"
    elif rid == "R5":
        v_str = f"{rule.value:+.1f} kg" if rule.value is not None else "Not computed"
        l_str = f">= {rule.limit:.1f} kg" if rule.limit is not None else "—"
    elif rid == "R9":
        v_str = f"{rule.value:.4f}" if rule.value is not None else "Not computed"
        l_str = "< 1 in 10,000" if rule.limit is not None else "—"
    else:
        v_str = f"{rule.value}" if rule.value is not None else "Not computed"
        l_str = f"{rule.limit}" if rule.limit is not None else "—"
    return v_str, l_str


def section_header(idx: str, title: str, blurb: str) -> str:
    """Render a section header with eyebrow, title and descriptor (§2.4)."""
    return (
        f'<div class="an-sechead"><div class="an-eyebrow">{esc(idx)}</div>'
        f'<h2>{esc(title)}</h2><p>{esc(blurb)}</p></div>'
    )


def _render_footer():
    """Render the persistent footer on every section (§2.5)."""
    from ananke import __version__ as app_version
    st.markdown('<div class="ananke-footer">', unsafe_allow_html=True)

    # Roadmap items — three across in a horizontal row.
    ROADMAP_ITEMS = [
        ("map", "Population Density Map"),
        ("hub", "Fleet &amp; Constellation Screening"),
        ("verified", "NASA DAS / ESA DRAMA Benchmark"),
    ]
    road_cols = st.columns(3)
    for idx, (_glyph, _label) in enumerate(ROADMAP_ITEMS):
        with road_cols[idx]:
            st.markdown(
                f'<div class="ananke-roadmap-row">'
                f'<span class="ananke-roadmap-icon">{_glyph}</span>'
                f'<span class="ananke-roadmap-label">{_label}</span>'
                f'<span class="ananke-roadmap-pill">Stage 2</span>'
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # Disclaimer + version + Tracr credit (§2.5).
    footer_line = (
        f'<span class="ananke-credit-text">'
        f'Ananke {esc(app_version)} '
        f'\u00b7 Screening tool, not a regulatory certificate '
        f'\u00b7 <span class="tracr-credit">Tracr Aerospace</span>'
        f'</span>'
    )
    credit_logo, credit_text = st.columns([1, 12], vertical_alignment="center")
    with credit_logo:
        st.image("assets/Tracr_Aerospace_Submark_Logo.png", width=26)
    with credit_text:
        st.markdown(footer_line, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# Navigation label ↔ internal key mapping. The segmented_control shows friendly
# labels; the existing if/elif/elif logic uses internal keys ("setup"/"results"/
# "dossier") — these two dicts bridge the gap without renaming anything.
NAV_ITEMS = [
    ("setup", "Mission Setup", ":material/rocket_launch:"),
    ("results", "Results", ":material/fact_check:"),
    ("dossier", "Dossier", ":material/description:"),
]
LABEL_TO_NAV = {"Mission Setup": "setup", "Results": "results", "Dossier": "dossier"}
NAV_TO_LABEL = {v: k for k, v in LABEL_TO_NAV.items()}

# Consistent radius scale.
_RECT_RADIUS = "8px"   # cards — small radii per design plan
_PILL_RADIUS = "999px"  # nav pill, buttons — fully rounded ends

# --------------------------------------------------------------------------- #
# Brand CSS. Assembled with string.Template ($NAME placeholders) rather than an
# f-string so the many literal CSS braces don't need escaping. $NAV is the
# active section, used to highlight only the current nav segment.
#
# Merged with design-plan §1.3 tokens CSS. Shape/elevation: hairline borders,
# no decorative shadows (except the nav pill), small radii (4–8 px).
# --------------------------------------------------------------------------- #

_CSS = Template(textwrap.dedent(
    """
    <style>
    /* Explicit system font stack for the whole app (HIG-style native feel). */
    html, body, .block-container, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
            Helvetica, Arial, sans-serif;
    }

    /* ---------- layout ---------- */
    .block-container{max-width:1280px;padding-top:1.5rem;padding-bottom:3rem}

    /* ---------- sticky-context fix ---------- */
    /* Streamlit wraps all content in section.stMain (overflow-y: auto, the
       real scroll container) > div.stMainBlockContainer > div.stVerticalBlock.
       For position: sticky to work on .st-key-ananke-pill-nav, EVERY element
       between the scroll container and the sticky element must have
       overflow: visible. Force it on the two known intermediate wrappers. */
    section.stMain > div.stMainBlockContainer,
    section.stMain > div.stMainBlockContainer > div.stVerticalBlock {
        overflow: visible !important;
    }

    /* ---------- numbers ---------- */
    .an-num{font-variant-numeric:tabular-nums lining-nums;font-feature-settings:"tnum" 1,"lnum" 1}

    /* ---------- section header ---------- */
    .an-eyebrow{font:600 .72rem/1.2 var(--an-font);letter-spacing:.08em;text-transform:uppercase;color:var(--an-muted)}
    .an-sechead h2{font:600 1.5rem/1.25 var(--an-font);color:var(--an-navy);margin:.25rem 0 .25rem;padding:0}
    .an-sechead p{font:400 .9rem/1.5 var(--an-font);color:var(--an-muted);margin:0 0 var(--an-s4);max-width:62ch}

    /* ---------- metric card (value / unit / label) ---------- */
    .an-metric{border:1px solid var(--an-earth);border-left-width:3px;border-radius:var(--an-r-card);
      background:var(--an-white);padding:var(--an-s4);height:100%;box-sizing:border-box}
    .an-metric[data-status="pass"]{border-left-color:var(--an-pass)}
    .an-metric[data-status="fail"]{border-left-color:var(--an-fail)}
    .an-metric[data-status="warn"]{border-left-color:var(--an-warn)}
    .an-metric[data-status="needs-input"]{border-left-color:var(--an-need)}
    .an-metric[data-status="infeasible"]{border-left-color:var(--an-fail)}
    .an-metric__head{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--an-s2)}
    .an-metric__label{font:600 .72rem/1.3 var(--an-font);letter-spacing:.06em;text-transform:uppercase;color:var(--an-muted)}
    .an-metric__row{display:flex;align-items:baseline;gap:var(--an-s2);margin:var(--an-s2) 0 var(--an-s1)}
    .an-metric__value{font:600 2.25rem/1 var(--an-font);letter-spacing:-.01em;color:var(--an-navy)}
    .an-metric__unit{font:500 .95rem/1 var(--an-font);color:var(--an-muted)}
    .an-metric__sub{font:400 .8rem/1.5 var(--an-mono);color:var(--an-muted)}
    .an-metric__basis{font:400 .75rem/1.45 var(--an-font);color:var(--an-muted);
      margin-top:var(--an-s3);padding-top:var(--an-s2);border-top:1px solid var(--an-earth)}

    /* ---------- status chips (stamp style, text-first) ---------- */
    .an-chip{display:inline-block;font:600 .68rem/1 var(--an-font);letter-spacing:.06em;text-transform:uppercase;
      padding:.3rem .5rem;border:1px solid;border-radius:var(--an-r-chip);white-space:nowrap}
    .an-chip--pass{color:var(--an-pass);background:var(--an-pass-bg);border-color:var(--an-pass-line)}
    .an-chip--fail,.an-chip--infeasible{color:var(--an-fail);background:var(--an-fail-bg);border-color:var(--an-fail-line)}
    .an-chip--warn{color:var(--an-warn);background:var(--an-warn-bg);border-color:var(--an-warn-line)}
    .an-chip--needs-input{color:var(--an-need);background:var(--an-need-bg);border-color:var(--an-need-line)}

    /* ---------- provenance tags: differ by border grammar, not hue ---------- */
    .an-tag{display:inline-block;font:600 .66rem/1 var(--an-font);letter-spacing:.06em;text-transform:uppercase;
      padding:.28rem .45rem;border-radius:var(--an-r-chip);border:1px solid;white-space:nowrap;margin-right:var(--an-s1)}
    .an-tag--physics{background:var(--an-navy);color:var(--an-white);border-color:var(--an-navy)}
    .an-tag--rules{background:transparent;color:var(--an-navy);border-color:var(--an-navy)}
    .an-tag--optimiser{background:transparent;color:var(--an-band-dark);border-color:var(--an-band-dark)}
    .an-tag--ml{background:transparent;color:var(--an-muted);border-color:var(--an-muted);border-style:dashed}

    /* ---------- key/value block (glass-box calculation) ---------- */
    .an-kv{display:grid;grid-template-columns:max-content 1fr;gap:.4rem var(--an-s4);margin:0;font-size:.85rem}
    .an-kv dt{color:var(--an-muted)}
    .an-kv dd{margin:0;font-family:var(--an-mono);color:var(--an-navy);overflow-wrap:anywhere}

    /* ---------- mission strip ---------- */
    .an-strip{display:flex;flex-wrap:wrap;gap:var(--an-s2) var(--an-s4);align-items:center;justify-content:space-between;
      padding:var(--an-s2) var(--an-s3);background:var(--an-surface);border:1px solid var(--an-earth);
      border-radius:var(--an-r-ctl);font:400 .8rem/1.3 var(--an-mono);color:var(--an-navy);margin-bottom:var(--an-s5)}
    .an-strip b{font-weight:600}

    /* ---------- readiness bar (counts, never a score) ---------- */
    .an-ready{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--an-earth)}
    .an-ready i{display:block;height:100%}
    .an-ready .p{background:var(--an-pass)} .an-ready .w{background:var(--an-warn)}
    .an-ready .f{background:var(--an-fail)} .an-ready .n{background:var(--an-need)}

    /* ---------- before/after comparison table ---------- */
    .an-cmp{width:100%;border-collapse:collapse;font-size:.875rem}
    .an-cmp th{text-align:left;font:600 .72rem/1.2 var(--an-font);letter-spacing:.06em;text-transform:uppercase;
      color:var(--an-muted);padding:var(--an-s2) var(--an-s3);border-bottom:1px solid var(--an-border-strong);background:var(--an-surface)}
    .an-cmp td{padding:var(--an-s2) var(--an-s3);border-bottom:1px solid var(--an-earth);font-variant-numeric:tabular-nums}
    .an-cmp td.num,.an-cmp th.num{text-align:right}
    .an-cmp td.num{font-family:var(--an-mono)}
    .an-cmp tr.is-changed td{background:var(--an-band-wash)}

    /* ---------- notices (replace st.warning / st.error / st.info) ---------- */
    .an-note{border:1px solid var(--an-earth);border-left-width:3px;border-radius:var(--an-r-ctl);
      padding:var(--an-s3) var(--an-s4);font-size:.875rem;line-height:1.5;color:var(--an-navy);background:var(--an-white)}
    .an-note--info{border-left-color:var(--an-band)}
    .an-note--warn{border-left-color:var(--an-warn);background:var(--an-warn-bg)}
    .an-note--fail{border-left-color:var(--an-fail);background:var(--an-fail-bg)}

    /* ---------- keyed Streamlit containers ---------- */
    [class*="st-key-card-"]{border-radius:var(--an-r-card)!important;border-color:var(--an-earth)!important;box-shadow:none!important}
    [class*="st-key-ruleitem-"] details{border:1px solid var(--an-earth)!important;border-left-width:3px!important;
      border-radius:var(--an-r-card)!important;margin-bottom:var(--an-s2);background:var(--an-white)}
    [class*="st-key-ruleitem-pass-"] details{border-left-color:var(--an-pass)!important}
    [class*="st-key-ruleitem-fail-"] details{border-left-color:var(--an-fail)!important}
    [class*="st-key-ruleitem-warn-"] details{border-left-color:var(--an-warn)!important}
    [class*="st-key-ruleitem-needs-input-"] details{border-left-color:var(--an-need)!important}
    [class*="st-key-pane-physics"]{border-left:3px solid var(--an-navy)!important}
    [class*="st-key-pane-ml"]{border-style:dashed!important}

    /* --- Buttons: filled Band Dark, sized to content, pill-shaped. --- */
    div.stButton > button,
    div.stDownloadButton > button {
        background-color: $JUPITER_BAND_DARK;
        color: #FFFFFF;
        border: none;
        border-radius: $PILL_RADIUS;
        padding: 0.45rem 1.1rem;
        font-weight: 600;
        width: fit-content;
        min-width: 220px;
        box-shadow: none;
    }
    div.stButton > button:hover,
    div.stDownloadButton > button:hover {
        background-color: $BAND_HOVER;
        color: #FFFFFF;
    }
    div.stButton > button:focus,
    div.stDownloadButton > button:focus {
        color: #FFFFFF;
        box-shadow: none;
    }
    /* Instant press feedback: quick scale-down the moment the button is pressed. */
    div.stButton > button:active,
    div.stDownloadButton > button:active {
        transform: scale(0.97);
        transition: transform 80ms ease-out;
    }
    /* Accessible focus: visible outline for keyboard navigation only. */
    div.stButton > button:focus-visible,
    div.stDownloadButton > button:focus-visible {
        outline: 2px solid $ANANKE_NAVY;
        outline-offset: 2px;
    }

    /* Breathing room + slight negative tracking on the larger card header text. */
    .block-container h3 {
        margin-top: 1.4rem;
        letter-spacing: -0.01em;
    }

    /* Bordered cards: hairline border, small radius, no shadow. */
    div[data-testid="stVerticalBlock"][data-test-scroll-behavior]:not([class*="st-key-"]) {
        border-radius: $RECT_RADIUS;
    }

    /* Input fields, selectboxes, number inputs: consistent small radius. */
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input {
        border-radius: var(--an-r-ctl);
    }
    /* Baseweb selectbox container. */
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
        border-radius: var(--an-r-ctl);
    }

    /* Extra whitespace between major card sections for a more "breathing" layout. */
    div[data-testid="stVerticalBlock"][data-test-scroll-behavior]:not([class*="st-key-"]) {
        margin-bottom: 1.2rem;
    }

    /* ============================================================ */
    /* Streamlit top app header — transparent so floating pill nav is visible */
    header[data-testid="stHeader"],
    .stAppHeader {
        background: transparent !important;
    }

    /* Outer wrapper — sticky pill nav and its parent container in Streamlit DOM */
    div:has(> .st-key-ananke-pill-nav) {
        position: sticky;
        top: 0;
        z-index: 100;
    }
    .st-key-ananke-pill-nav {
        position: sticky;
        top: 0;
        z-index: 100;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0.6rem 0 0.3rem 0;
        /* Translucent Orbit White + frosted glass blur. */
        background: rgba(254, 254, 254, 0.85);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
    }

    /* Inner pill container (sits around the segmented control). */
    .ananke-pill-inner {
        display: inline-flex;
        align-items: center;
        gap: 0.75rem;
        background: rgba(254, 254, 254, 0.92);
        border-radius: $PILL_RADIUS;
        padding: 0.4rem 0.75rem 0.4rem 0.6rem;
        /* Nav pill is the only permitted shadow per the design plan. */
        box-shadow: 0 8px 24px rgba(12, 21, 32, 0.10),
                    0 2px 8px rgba(12, 21, 32, 0.06);
    }

    /* Submark image in the pill — keep compact. */
    .ananke-pill-submark img {
        display: block;
        width: 34px;
        height: 34px;
        object-fit: contain;
    }

    /* Segmented control styling — selected segment uses Jupiter Band Dark
       (#7F6144) with white text for WCAG AA compliance (5.68:1 contrast).
       Unselected segments: transparent, Ananke Navy text. */
    .st-key-nav_segment button[aria-pressed="true"] {
        background-color: $JUPITER_BAND_DARK !important;
        color: #FFFFFF !important;
        border-radius: $PILL_RADIUS !important;
        font-weight: 600;
    }
    .st-key-nav_segment button[aria-pressed="false"] {
        background-color: transparent !important;
        color: $ANANKE_NAVY !important;
        border-radius: $PILL_RADIUS !important;
        font-weight: 500;
    }
    .st-key-nav_segment button[aria-pressed="false"]:hover {
        background-color: rgba(159, 123, 89, 0.10) !important;
    }
    /* Hide the label above the segmented control (label_visibility="collapsed"
       handles the text, but ensure no residual space). */
    .st-key-nav_segment label {
        display: none !important;
    }

    /* Content offset below the sticky floating nav.
       Sticky nav rendered height: 48.39px (34px content + 9.6px [0.6rem] top padding + 4.8px [0.3rem] bottom padding).
       Top offset: 0px.
       Visual gap buffer: 20px.
       Exact padding-top: 48.39px + 0px + 20px = 68.39px. */
    .st-key-ananke-main-setup,
    .st-key-ananke-main-results,
    .st-key-ananke-main-dossier {
        padding-top: 68.39px;
    }

    /* ============================================================ */
    /* Footer (Roadmap + Tracr credit)                               */
    /* ============================================================ */

    .ananke-footer {
        margin-top: 3rem;
        padding-top: 1.5rem;
        border-top: 1px solid var(--an-earth);
    }

    /* ROADMAP rows: flat, inert, no button/hover/pointer. */
    .ananke-roadmap-row {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        opacity: 0.55;
        color: $ANANKE_NAVY;
        font-size: 0.85rem;
        padding: 0.3rem 0.6rem;
        cursor: default;
    }
    .ananke-roadmap-icon {
        font-family: 'Material Symbols Rounded';
        font-weight: normal;
        font-style: normal;
        font-size: 1.05rem;
        line-height: 1;
        white-space: nowrap;
        -webkit-font-feature-settings: 'liga';
        font-feature-settings: 'liga';
        font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
    }
    .ananke-roadmap-label {
        flex: 1 1 auto;
    }
    .ananke-roadmap-pill {
        font-size: 0.7rem;
        font-weight: 600;
        background: rgba(159, 123, 89, 0.14);
        color: $JUPITER_BAND_DARK;
        border-radius: 6px;
        padding: 0.05rem 0.4rem;
        white-space: nowrap;
    }

    .ananke-credit-text {
        font-size: 0.8rem;
        color: #6B7580;
        line-height: 1.35;
    }
    .tracr-credit {
        color: $TRACR_INDIGO;
        font-weight: 600;
    }

    /* ============================================================ */
    /* Main-content entrance motion.                                 */
    /* A CSS replay trick, not a true interruptible spring: the      */
    /* container is keyed per section (st-key-ananke-main-<nav>), so */
    /* switching sections remounts the node and the fade-in replays. */
    /* No bounce / overshoot. Respects reduced-motion.               */
    /* ============================================================ */
    @keyframes ananke-fade-in {
        from { opacity: 0; transform: translateY(6px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @media (not (prefers-reduced-motion: reduce)) {
        .st-key-ananke-main-setup,
        .st-key-ananke-main-results,
        .st-key-ananke-main-dossier {
            animation: ananke-fade-in 220ms ease-out;
        }
    }
    </style>
    """
))

st.markdown(
    f"<style>{root_css()}</style>"
    + _CSS.substitute(
        JUPITER_BAND_DARK=JUPITER_BAND_DARK,
        BAND_HOVER=TOKENS["band_hover"],
        ANANKE_NAVY=ANANKE_NAVY,
        TRACR_INDIGO=TRACR_INDIGO,
        NAV=nav,
        RECT_RADIUS=_RECT_RADIUS,
        PILL_RADIUS=_PILL_RADIUS,
    ),
    unsafe_allow_html=True,
)

# Rule-table status colors — a touch more saturated than the pastel defaults,
# same green/red/amber/grey family, still readable with navy text.
STATUS_COLORS = {
    "PASS": "background-color: #9BDBA5",
    "FAIL": "background-color: #F2A7AE",
    "WARN": "background-color: #FFDD70",
    "NEEDS_INPUT": "background-color: #CFCFCD",
}

# Displayed Status-column text. Plain status words only — the :material:
# shorthand does not render inside a pandas DataFrame cell (it would show as
# literal text), so we keep the words and rely on the background-color styling.
STATUS_DISPLAY = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "WARN": "WARN",
    "NEEDS_INPUT": "NEEDS_INPUT",
}


@st.cache_resource
def _get_surrogate():
    """Train the ML lifetime surrogate once per server process (cached).

    Returns ``(model, metrics)``. Training happens on first access only; every
    later screening reuses the same fitted model, so the 10k-sample / 200-tree
    fit is paid once at startup rather than on every run. This model is a fast
    preview only — it never drives a compliance (PASS/FAIL) decision.
    """
    df = generate_training_data(10000, seed=42)
    model, metrics = train_surrogate(df, random_state=42)
    return model, metrics


# --------------------------------------------------------------------------- #
# Floating pill nav bar — submark + segmented control.
# --------------------------------------------------------------------------- #

with st.container(key="ananke-pill-nav"):
    # Build the pill visually: submark image on the left, segmented control
    # on the right, both wrapped in a pill-shaped inner container.
    # Use a narrow left column for the submark, wider right column for segments.
    pill_left, pill_right = st.columns([1, 12], vertical_alignment="center")
    with pill_left:
        st.image("assets/Ananke_SUBMARK_Logo.png", width=34)
    with pill_right:
        nav_choice = st.segmented_control(
            "Navigation",
            options=["Mission Setup", "Results", "Dossier"],
            default=NAV_TO_LABEL.get(nav, "Mission Setup"),
            label_visibility="collapsed",
            key="nav_segment",
        )
        # Map the selected label back to the internal key. If the user clicked
        # a new segment, update session_state and rerun (same pattern as the
        # old sidebar buttons).
        if nav_choice is not None:
            new_nav = LABEL_TO_NAV.get(nav_choice, "setup")
            if new_nav != st.session_state["nav"]:
                st.session_state["nav"] = new_nav
                st.rerun()


# --------------------------------------------------------------------------- #
# Main content — one section at a time, chosen by st.session_state["nav"].
# The container is keyed per section (ananke-main-<nav>) so switching remounts
# it and the entrance fade-in replays (see CSS note).
# --------------------------------------------------------------------------- #

with st.container(key=f"ananke-main-{nav}"):
    if nav == "setup":
        st.markdown(
            section_header(
                "01 \u00b7 Mission setup",
                "Describe the mission",
                "Enter the design. Each card lists the rules its inputs feed.",
            ),
            unsafe_allow_html=True,
        )

        # Card 1 — Mission & Spacecraft.
        with st.container(border=True):
            st.subheader(":material/satellite_alt: Mission & Spacecraft")
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Mission name", value="EO-DEMO-1")
            with c2:
                mission_life_yr = st.number_input("Mission life (years)", value=5.0)
            c3, c4, c5 = st.columns(3)
            with c3:
                mass_kg = st.number_input("Mass (kg)", value=120.0)
            with c4:
                area_m2 = st.number_input("Mean cross-section area (m^2)", value=1.2)
            with c5:
                cd = st.number_input("Drag coefficient Cd", value=2.2)

        # Card 2 — Orbit.
        with st.container(border=True):
            st.subheader(":material/public: Orbit")
            c1, c2 = st.columns(2)
            with c1:
                altitude_km = st.number_input("Altitude (km)", value=750.0)
            with c2:
                inclination_deg = st.number_input("Inclination (deg)", value=97.4)

        # Card 3 — Propulsion.
        with st.container(border=True):
            st.subheader(":material/local_fire_department: Propulsion")
            c1, c2 = st.columns(2)
            with c1:
                prop_type = st.selectbox(
                    "Propulsion type",
                    options=PROPULSION_OPTIONS,
                    index=PROPULSION_OPTIONS.index("monoprop"),
                )
            with c2:
                isp_s = st.number_input("Specific impulse Isp (s)", value=220.0)
            c3, c4, c5 = st.columns(3)
            with c3:
                propellant_kg = st.number_input("Propellant available (kg)", value=10.0)
            with c4:
                reliability = st.number_input(
                    "Disposal reliability (0-1)",
                    value=0.995,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.001,
                )
            with c5:
                p_collision = st.number_input(
                    "Collision probability (0-1)",
                    value=0.002,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.001,
                    format="%.4f",
                )

        # Card 4 — Disposal Plan.
        with st.container(border=True):
            st.subheader(":material/flight_land: Disposal Plan")
            c1, c2 = st.columns(2)
            with c1:
                strategy = st.selectbox(
                    "Disposal strategy",
                    options=DISPOSAL_OPTIONS,
                    index=DISPOSAL_OPTIONS.index("lower_to_circular"),
                )
            with c2:
                no_target = st.checkbox(
                    "No target altitude (natural decay / undecided)", value=False
                )
            target_alt_km_input = st.number_input("Target altitude (km)", value=500.0)

            # Re-entry casualty inputs — only shown for a controlled re-entry.
            reentry_data = None
            if strategy == "controlled_reentry":
                with st.expander("Re-entry casualty inputs"):
                    n_components = int(
                        st.number_input(
                            "How many surviving components",
                            min_value=1,
                            max_value=5,
                            value=1,
                            step=1,
                        )
                    )
                    components = []
                    for i in range(n_components):
                        st.markdown(f"**Component {i + 1}**")
                        c_mass = st.number_input(
                            f"Mass (kg) — component {i + 1}", value=5.0, key=f"comp_mass_{i}"
                        )
                        c_area = st.number_input(
                            f"Area (m^2) — component {i + 1}", value=0.5, key=f"comp_area_{i}"
                        )
                        components.append({"mass_kg": c_mass, "area_m2": c_area})

                    nominal_rho = st.number_input(
                        "Nominal population density (people/km^2)", value=15.0
                    )
                    failure_rho = st.number_input(
                        "Failure-case population density (people/km^2)", value=15.0
                    )
                    p_fail = st.number_input(
                        "Manoeuvre failure probability (0-1)",
                        value=0.05,
                        min_value=0.0,
                        max_value=1.0,
                        step=0.01,
                    )

                    # Optional, illustrative-only target location (not used in the Ec calc).
                    target_lat = None
                    target_lon = None
                    has_location = st.checkbox(
                        "I have an approximate target re-entry location", value=False
                    )
                    if has_location:
                        target_lat = st.number_input(
                            "Target latitude (deg)",
                            min_value=-90.0,
                            max_value=90.0,
                            value=19.0760,
                        )
                        target_lon = st.number_input(
                            "Target longitude (deg)",
                            min_value=-180.0,
                            max_value=180.0,
                            value=72.8777,
                        )

                    reentry_data = {
                        "components": components,
                        "nominal_rho_eff_per_km2": nominal_rho,
                        "failure_rho_eff_per_km2": failure_rho,
                        "p_fail": p_fail,
                        "target_lat": target_lat,
                        "target_lon": target_lon,
                    }

        # Card 5 — Compliance Checklist.
        with st.container(border=True):
            st.subheader(":material/checklist: Compliance Checklist")
            c1, c2, c3 = st.columns(3)
            with c1:
                passivation = st.checkbox("Passivation", value=True)
            with c2:
                trackable = st.checkbox("Trackable", value=True)
            with c3:
                insurance = st.checkbox("Insurance", value=False)

        st.markdown("")

        # Primary call-to-action. Sized to content via CSS (width: fit-content +
        # min-width floor); no longer stretched full-width.
        if st.button(
            "Run Screening",
            icon=":material/search:",
            type="primary",
        ):
            target_alt_km = None if no_target else target_alt_km_input

            data = {
                "name": name,
                "mass_kg": mass_kg,
                "area_m2": area_m2,
                "cd": cd,
                "orbit": {
                    "type": "circular",
                    "altitude_km": altitude_km,
                    "inclination_deg": inclination_deg,
                },
                "mission_life_yr": mission_life_yr,
                "propulsion": {
                    "type": prop_type,
                    "isp_s": isp_s,
                    "propellant_kg": propellant_kg,
                    "reliability": reliability,
                },
                "p_collision": p_collision,
                "disposal": {"strategy": strategy, "target_alt_km": target_alt_km},
                "checklist": {
                    "passivation": passivation,
                    "trackable": trackable,
                    "insurance": insurance,
                },
                "reentry": reentry_data,
            }

            try:
                mission = MissionInput(**data)
            except Exception as exc:  # pydantic ValidationError or similar
                st.error(f"Invalid input: {exc}")
                st.session_state.pop("results", None)
                st.session_state.pop("pdf_bytes", None)
            else:
                output = screen_mission(mission)
                optimiser_result = find_cheapest_designs(
                    mass_kg=mission.mass_kg,
                    cd=mission.cd,
                    area_m2=mission.area_m2,
                    isp_s=mission.propulsion.isp_s,
                    propellant_available_kg=mission.propulsion.propellant_kg,
                    desired_altitude_km=mission.orbit.altitude_km,
                )
                st.session_state["results"] = {
                    "mission": mission,
                    "output": output,
                    "optimiser": optimiser_result,
                }
                # A fresh screening invalidates any previously generated PDF.
                st.session_state.pop("pdf_bytes", None)
                st.success(
                    "Screening complete — see the Results section.",
                    icon=":material/check_circle:",
                )

    elif nav == "results":
        st.markdown(
            section_header(
                "02 \u00b7 Results",
                "Screening result",
                "Each result shows what was calculated, from which inputs, against which limit and source.",
            ),
            unsafe_allow_html=True,
        )
        if "results" not in st.session_state:
            st.info(
                "Fill in a mission in Mission Setup and click Run "
                "Screening to see results here.",
                icon=":material/arrow_back:",
            )
        else:
            mission = st.session_state["results"]["mission"]
            output = st.session_state["results"]["output"]
            optimiser_result = st.session_state["results"]["optimiser"]

            # Readiness counts (same calculation as before).
            total = len(output.rules)
            n_pass = sum(1 for r in output.rules if r.status.value == "PASS")

            # Status for Card 1 (Readiness):
            # FAIL if hard safety rule (R1 or R2) fails, PASS if all rules pass, otherwise WARN.
            status_by_id = {r.id: r.status.value for r in output.rules}
            safety_fail = (
                status_by_id.get("R1") == "FAIL" or status_by_id.get("R2") == "FAIL"
            )
            if safety_fail:
                readiness_status = "FAIL"
            elif n_pass == total:
                readiness_status = "PASS"
            else:
                readiness_status = "WARN"

            # Card 1 — Readiness
            card1_html = metric_card(
                "RULES PASS",
                f"{n_pass}",
                unit=f"/ {total}",
                status=readiness_status,
            )

            # Card 2 — Orbital lifetime
            r1 = next((r for r in output.rules if r.id == "R1"), None)
            if output.lifetime_years is not None:
                c2_val = f"{output.lifetime_years.nominal:.1f}"
                c2_unit = "yr"
                c2_status = r1.status if r1 else None
                c2_sub = (
                    f"Best {output.lifetime_years.best:.1f} · "
                    f"Worst {output.lifetime_years.worst:.1f} yr"
                )
                c2_basis = "Rule R1 is evaluated on the worst-case value."
                c2_tag = "physics"
            else:
                c2_val = "—"
                c2_unit = "yr"
                c2_status = None
                c2_sub = "Lifetime not available (missing input)."
                c2_basis = None
                c2_tag = None

            card2_html = metric_card(
                "ORBITAL LIFETIME (POST-DISPOSAL)",
                c2_val,
                unit=c2_unit,
                status=c2_status,
                sub=c2_sub,
                basis=c2_basis,
                tag_kind=c2_tag,
            )

            # Card 3 — Disposal success probability
            r2 = next((r for r in output.rules if r.id == "R2"), None)
            if r2 is not None and r2.value is not None:
                c3_val = f"{r2.value:.3f}"
                c3_sub = None
                c3_basis = f"Limit: {r2.limit}"
                c3_tag = "physics"
            else:
                c3_val = "—"
                c3_sub = "Cannot be evaluated: required input missing."
                c3_basis = None
                c3_tag = None
            c3_status = r2.status if r2 else None

            card3_html = metric_card(
                "DISPOSAL SUCCESS PROBABILITY",
                c3_val,
                unit="",
                status=c3_status,
                sub=c3_sub,
                basis=c3_basis,
                tag_kind=c3_tag,
            )

            # Card 4 — Fuel margin
            r5 = next((r for r in output.rules if r.id == "R5"), None)
            if r5 is not None and r5.value is not None:
                c4_val = f"{r5.value:+.1f}"
                c4_sub = None
                c4_basis = (
                    "Positive margin means propellant available exceeds what the "
                    "disposal burn requires."
                )
                c4_tag = "physics"
            else:
                c4_val = "—"
                c4_sub = "Cannot be evaluated: required input missing."
                c4_basis = None
                c4_tag = None
            c4_status = r5.status if r5 else None

            card4_html = metric_card(
                "DISPOSAL FUEL MARGIN",
                c4_val,
                unit="kg",
                status=c4_status,
                sub=c4_sub,
                basis=c4_basis,
                tag_kind=c4_tag,
            )

            # Headline stat-card row.
            head_a, head_b, head_c, head_d = st.columns(4)
            with head_a:
                st.markdown(card1_html, unsafe_allow_html=True)
            with head_b:
                st.markdown(card2_html, unsafe_allow_html=True)
            with head_c:
                st.markdown(card3_html, unsafe_allow_html=True)
            with head_d:
                st.markdown(card4_html, unsafe_allow_html=True)

            # AI Fast Preview (ML surrogate). The surrogate predicts natural-decay
            # lifetime at the OPERATIONAL altitude; we compare it against the exact
            # physics value at that SAME altitude and k=1.0, so the two numbers are
            # apples-to-apples. output.lifetime_years.nominal is deliberately NOT
            # reused here — it is the post-disposal lifetime (a different altitude),
            # so comparing it to the surrogate would be misleading.
            st.subheader("AI Fast Preview (ML Surrogate)")
            _model, _ml_metrics = _get_surrogate()
            op_alt_km = mission.orbit.altitude_km
            B_mission = ballistic_coefficient(
                mission.mass_kg, mission.cd, mission.area_m2
            )
            ml_years = predict_lifetime_years(
                _model, mission.mass_kg, mission.cd, mission.area_m2, op_alt_km, 1.0
            )
            physics_years = lifetime_years(op_alt_km, B_mission, k=1.0)
            st.caption(
                f"Estimated natural-decay lifetime from the operational altitude "
                f"({op_alt_km:.0f} km, nominal solar activity), shown against the exact "
                "physics value at the same altitude so the two are directly comparable. "
                "This differs from the post-disposal \u201cNominal (yr)\u201d figure above, which "
                "is measured after the disposal manoeuvre."
            )
            col_ml, col_phys = st.columns(2)
            with col_ml:
                st.metric("ML Surrogate (fast estimate)", f"{ml_years:.1f} yr")
            with col_phys:
                st.metric("Physics Engine (authoritative)", f"{physics_years:.1f} yr")
            st.caption(
                f"Trained on {_ml_metrics['n_train']} simulated missions, validated on "
                f"{_ml_metrics['n_holdout']} held out. Log-space R\u00b2 = "
                f"{_ml_metrics['r2_log_space']:.3f} (the metric the model is trained "
                f"against); year-space R\u00b2 = {_ml_metrics['r2']:.3f} (lower, because a few "
                "extreme-lifetime outliers dominate raw variance \u2014 median error on "
                f"realistic missions is {_ml_metrics['median_ape_pct']:.1f}%, mean "
                f"absolute error {_ml_metrics['mae_years']:.2f} yr). This estimate is for "
                "fast preview only \u2014 rule compliance (PASS/FAIL) always uses the exact "
                "physics engine above, never this surrogate."
            )

            # Detail sections.
            rule_filter = st.segmented_control(
                "Filter rules",
                options=["All", "Needs attention", "Passing"],
                default="All",
                label_visibility="collapsed",
                key="rules_filter_choice",
            )

            if rule_filter == "Needs attention":
                filtered_rules = [
                    r for r in output.rules
                    if (r.status.value if hasattr(r.status, "value") else str(r.status)) in {"FAIL", "WARN", "NEEDS_INPUT"}
                ]
            elif rule_filter == "Passing":
                filtered_rules = [
                    r for r in output.rules
                    if (r.status.value if hasattr(r.status, "value") else str(r.status)) == "PASS"
                ]
            else:
                filtered_rules = list(output.rules)

            CATALOGUE_ORDER = ["R1", "R2", "R3", "R5", "R9"]
            filtered_rules.sort(
                key=lambda r: CATALOGUE_ORDER.index(r.id) if r.id in CATALOGUE_ORDER else 999
            )

            tab_detail, tab_table = st.tabs(["Rule detail", "Table view"])

            with tab_detail:
                if not filtered_rules:
                    st.info("No rules match the current filter.")
                else:
                    first_fail_seen = False
                    for rule in filtered_rules:
                        status_str = rule.status.value if hasattr(rule.status, "value") else str(rule.status)
                        is_fail = (status_str == "FAIL")
                        is_first_fail = False
                        if is_fail and not first_fail_seen:
                            is_first_fail = True
                            first_fail_seen = True

                        rule_title = RULE_TITLES.get(rule.id, "")
                        v_label, l_label = format_rule_label_values(rule)
                        expander_label = (
                            f"**{STATUS_LABEL.get(rule.status, status_str)}** · "
                            f"**{rule.id}** {rule_title} — `{v_label}` vs `{l_label}`"
                        )

                        with st.container(key=f"ruleitem-{skey(rule.status)}-{rule.id}"):
                            with st.expander(expander_label, expanded=is_first_fail):
                                col_left, col_right = st.columns([5, 6])
                                with col_left:
                                    st.markdown(
                                        f'<div class="an-eyebrow" style="margin-bottom:0.35rem;">Requirement</div>'
                                        f'<div style="font-size:0.92rem; line-height:1.45; color:var(--an-navy); margin-bottom:0.5rem;">'
                                        f'{esc(RULE_DETAIL[rule.id]["requirement"])}'
                                        f'</div>'
                                        f'<div style="margin-bottom:0.85rem;">'
                                        f'<span class="an-tag an-tag--rules">HARD RULE</span>'
                                        f'</div>'
                                        f'<div class="an-eyebrow" style="margin-bottom:0.35rem;">Source</div>'
                                        f'<div style="font-size:0.88rem; color:var(--an-muted);">'
                                        f'{esc(rule.source if rule.source else "—")}'
                                        f'</div>',
                                        unsafe_allow_html=True,
                                    )

                                with col_right:
                                    st.markdown(
                                        '<div class="an-eyebrow" style="margin-bottom:0.35rem;">Calculation</div>',
                                        unsafe_allow_html=True,
                                    )
                                    if status_str == "NEEDS_INPUT":
                                        if rule.note:
                                            st.markdown(note("warn", rule.note), unsafe_allow_html=True)
                                        st.button(
                                            "Go to Mission Setup",
                                            key=f"goto-{rule.id}",
                                            on_click=lambda: st.session_state.update(
                                                nav="setup", nav_segment="Mission Setup"
                                            ),
                                        )
                                    else:
                                        detail = RULE_DETAIL[rule.id]
                                        if rule.value is None:
                                            computed_val = "Not computed"
                                        elif rule.id == "R3":
                                            computed_val = (
                                                "No crossing" if rule.value == 0.0 else "Crosses the protected band"
                                            )
                                        elif rule.id == "R1":
                                            computed_val = f"{rule.value:.2f} yr"
                                        elif rule.id == "R2":
                                            computed_val = f"{rule.value:.3f}"
                                        elif rule.id == "R5":
                                            computed_val = f"{rule.value:+.1f} kg"
                                        else:
                                            computed_val = f"{rule.value}"

                                        kv_pairs = [
                                            ("Inputs used", detail["inputs"]),
                                            ("Method", detail["method"]),
                                            ("Computed", computed_val),
                                        ]

                                        if rule.id != "R3":
                                            if rule.id == "R1":
                                                thresh_val = f"< {rule.limit:.1f} yr" if rule.limit is not None else "—"
                                            elif rule.id == "R2":
                                                thresh_val = f"> {rule.limit:.2f}" if rule.limit is not None else "—"
                                            elif rule.id == "R5":
                                                thresh_val = f">= {rule.limit:.1f} kg" if rule.limit is not None else "—"
                                            elif rule.id == "R9":
                                                thresh_val = "< 1 in 10,000" if rule.limit is not None else "—"
                                            else:
                                                thresh_val = f"{rule.limit}" if rule.limit is not None else "—"
                                            kv_pairs.append(("Threshold", thresh_val))

                                        margin_val = compute_rule_margin(
                                            rule.id, rule.value, rule.limit, detail.get("limit_direction", "")
                                        )
                                        if margin_val is not None:
                                            kv_pairs.append(("Margin", margin_val))

                                        st.markdown(kv_block(kv_pairs), unsafe_allow_html=True)

            with tab_table:
                rows = [
                    {
                        "Rule ID": r.id,
                        "Status": STATUS_DISPLAY.get(r.status.value, r.status.value),
                        "Value": r.value,
                        "Limit": r.limit,
                        "Source": r.source,
                        "Note": r.note,
                    }
                    for r in output.rules
                ]
                df = pd.DataFrame(rows)

                def _color_status(val):
                    # Match on the status keyword within the cell text.
                    for key, css in STATUS_COLORS.items():
                        if key in val:
                            return css
                    return ""

                try:
                    styled = df.style.applymap(_color_status, subset=["Status"])
                    st.dataframe(styled, use_container_width=True)
                except Exception:
                    # Fall back to a plain table if styling is unavailable.
                    st.table(df)

            with st.expander(
                "AI Design Optimizer \u2014 Suggested Design Changes", expanded=True
            ):
                st.caption(
                    f"Searched {optimiser_result['total_candidates_evaluated']} "
                    "altitude/disposal-strategy combinations under worst-case solar "
                    "assumptions to find the cheapest compliant design."
                )
                if optimiser_result["status"] == "OK":
                    opt_rows = [
                        {
                            "Altitude (km)": round(c["altitude_km"], 1),
                            "Strategy": c["strategy"],
                            "Propellant needed (kg)": round(c["propellant_kg"], 1),
                        }
                        for c in optimiser_result["candidates"]
                    ]
                    st.table(pd.DataFrame(opt_rows))
                else:
                    st.warning(optimiser_result["message"])

            with st.expander("Trade-space Chart", expanded=True):
                # Propellant needed vs operational altitude, mission thruster vs a
                # cold-gas (Isp 60s) baseline (reproduces the blueprint's Figure 5).
                mission_isp = mission.propulsion.isp_s
                # Avoid a duplicate series if the mission thruster is already Isp 60s.
                if mission_isp == 60.0:
                    isp_list = [60.0]
                else:
                    isp_list = [mission_isp, 60.0]

                trade = propellant_vs_altitude(
                    mass_kg=mission.mass_kg,
                    cd=mission.cd,
                    area_m2=mission.area_m2,
                    isp_s_list=isp_list,
                    alt_min_km=450.0,
                    alt_max_km=800.0,
                    alt_step_km=10.0,
                )

                def _fmt_isp(v):
                    return str(int(v)) if float(v).is_integer() else str(v)

                # Labels generated from the actual Isp values (never hard-coded).
                thruster_name = mission.propulsion.type.value.replace("_", " ").title()
                labels = {
                    mission_isp: f"{thruster_name} (Isp {_fmt_isp(mission_isp)}s) \u2014 kg"
                }
                if 60.0 in isp_list and 60.0 != mission_isp:
                    labels[60.0] = f"Cold gas (Isp {_fmt_isp(60.0)}s) \u2014 kg"

                trade_cols = {"Altitude (km)": trade["altitudes_km"]}
                for isp in isp_list:
                    trade_cols[labels[isp]] = trade["propellant_by_isp"][isp]
                trade_df = pd.DataFrame(trade_cols)

                # Highest altitude at which the mission's own thruster needs zero
                # propellant (natural decay already satisfies the worst-case rule below it).
                mission_label = labels[mission_isp]
                zero_alts = trade_df.loc[
                    trade_df[mission_label] == 0.0, "Altitude (km)"
                ]
                if not zero_alts.empty:
                    threshold = zero_alts.max()
                    st.write(
                        f"For this spacecraft, altitudes at or below ~{threshold:.0f} km "
                        "require no disposal propellant at all (natural decay handles it)."
                    )
                else:
                    st.write(
                        "For this spacecraft, no altitude in the 450\u2013800 km range needs "
                        "zero disposal propellant (natural-decay threshold not reached "
                        "in this range)."
                    )

                st.line_chart(trade_df, x="Altitude (km)")
                st.caption(
                    "Propellant needed to bring the satellite down to a compliant "
                    "disposal orbit, if launched at each altitude on the x-axis. Below "
                    "the altitude where the line reaches zero, natural atmospheric drag "
                    "alone satisfies the 5-year disposal rule (worst-case), so no "
                    "propellant is needed."
                )

            # Illustrative re-entry map — only when coordinates were provided.
            if (
                mission.reentry is not None
                and mission.reentry.target_lat is not None
                and mission.reentry.target_lon is not None
            ):
                with st.expander("Re-entry Map", expanded=True):
                    lat = mission.reentry.target_lat
                    lon = mission.reentry.target_lon

                    target_layer = pdk.Layer(
                        "ScatterplotLayer",
                        data=[{"lon": lon, "lat": lat}],
                        get_position="[lon, lat]",  # pydeck expects [lon, lat] order
                        get_radius=50000,  # metres
                        get_fill_color=[159, 123, 89, 160],  # Jupiter Band, ~63% opacity
                        pickable=False,
                    )
                    view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=4)
                    # Use pydeck's default no-token basemap so the map renders without
                    # requiring a Mapbox API key to be configured.
                    deck = pdk.Deck(
                        layers=[target_layer],
                        initial_view_state=view_state,
                        map_style=None,
                    )
                    st.pydeck_chart(deck)
                    st.caption(
                        "Illustrative target location only. This map does not use real "
                        "population data. Full population-grid danger-zone mapping (using "
                        "WorldPop data) is a planned Stage 2 feature, not yet implemented."
                    )

            # Honest breakdown of what "AI" means in this tool (blueprint 9.7).
            with st.expander("About the AI in this tool"):
                st.markdown(
                    f"""
**What is and isn\u2019t AI here \u2014 and what\u2019s validated.**

- **Design-space search (classical AI).** The "AI Design Optimizer" above is a
  search-and-optimisation routine: it sweeps every altitude in the grid, prices
  each disposal option under worst-case solar activity, and returns the cheapest
  compliant design. This is classical AI (search/optimisation), not a learned
  model.
- **Physics models (not AI).** Orbital lifetime, delta-v, and re-entry casualty
  are deterministic textbook physics with their own unit tests \u2014 not AI, and not
  guesses. Every PASS/FAIL decision comes from these.
- **ML surrogate (a real, validated model \u2014 preview only).** The "AI Fast
  Preview" is a random forest trained on {_ml_metrics['n_train']} of our own
  physics simulations and validated on {_ml_metrics['n_holdout']} held-out cases.
  Log-space R\u00b2 = {_ml_metrics['r2_log_space']:.3f} (the metric it is trained
  against); year-space R\u00b2 = {_ml_metrics['r2']:.3f} is lower because a few
  extreme-lifetime outliers dominate raw variance \u2014 median error on realistic
  missions is {_ml_metrics['median_ape_pct']:.1f}% (mean absolute error
  {_ml_metrics['mae_years']:.2f} yr). It exists purely for a fast lifetime
  estimate and is **never** used to decide compliance \u2014 the physics engine
  always is.
- **What we do _not_ claim.** No deep learning, no reinforcement learning, and no
  predictive claim beyond this one trained, measured surrogate.
                    """
                )

            # Disclaimer stays visible at the bottom, outside any expander.
            st.info(output.disclaimer)
    elif nav == "dossier":
        st.markdown(
            section_header(
                "03 \u00b7 Dossier",
                "Draft debris mitigation plan",
                "A PDF of the inputs, assumptions, results and sources from the latest run. Screening only.",
            ),
            unsafe_allow_html=True,
        )
        if "results" not in st.session_state:
            st.info("Run a screening in Mission Setup first.")
        else:
            mission = st.session_state["results"]["mission"]
            output = st.session_state["results"]["output"]
            optimiser_result = st.session_state["results"]["optimiser"]

            if st.button("Generate Dossier PDF"):
                fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                try:
                    _, ml_metrics = _get_surrogate()
                    generate_dossier_pdf(
                        mission,
                        output,
                        optimiser_result,
                        ml_metrics=ml_metrics,
                        output_path=pdf_path,
                    )
                    with open(pdf_path, "rb") as fh:
                        st.session_state["pdf_bytes"] = fh.read()
                finally:
                    if os.path.exists(pdf_path):
                        os.unlink(pdf_path)

            if "pdf_bytes" in st.session_state:
                st.download_button(
                    "Download Dossier PDF",
                    data=st.session_state["pdf_bytes"],
                    file_name="ananke_dossier.pdf",
                    mime="application/pdf",
                )

            # Read-only preview of the PDF's contents (Step 19). Purely
            # descriptive — mirrors the section order generate_dossier_pdf writes.
            with st.container(border=True):
                st.markdown("**What's in this dossier**")
                st.markdown(
                    "- Mission Summary\n"
                    "- Orbital Lifetime Estimate\n"
                    "- Rule-by-Rule Compliance Results\n"
                    "- Suggested Design Changes\n"
                    "- Methods and Sources\n"
                    "- Disclaimer"
                )


# --------------------------------------------------------------------------- #
# Footer — Roadmap (inert Stage-2 items) + disclaimer + Tracr credit (§2.5).
# Sits below all section content, visible on every section.
# --------------------------------------------------------------------------- #

_render_footer()
