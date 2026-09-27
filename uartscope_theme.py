"""UARTScope Pro v2 — design tokens.

Single source of truth for the UI. No screen may hardcode a colour, radius,
type size, or shadow; if a value is needed that is not here, it gets added here
first, deliberately.

Design lineage
--------------
Apple's *typographic and spatial discipline*:
  - one accent colour, reserved for interactive elements
  - weight ceiling 700 (no 800/900)
  - negative letter-spacing at every size, not just headlines
  - headline leading 1.1, body leading 1.47
  - elevation by surface contrast, never stacked drop shadows
  - no gradient as decoration

Claude's *warm neutrals*:
  - every gray carries a yellow-brown undertone; no cool blue-gray
  - depth from warm ring shadows (0 0 0 1px), not drop shadows

Deliberately NOT adopted from Apple's marketing system: full-viewport
cinematic section pacing and centred heroes. Serial debugging is a *Monitor*
surface, where density and glanceability beat a hero. Copying a marketing
composition here would be composition-slop.

Contrast is computed, not eyeballed. Every pair used for text is recorded in
CONTRAST_AUDIT with its measured WCAG ratio. Values that failed were changed:
  - Claude's error crimson #b53333 measured 2.77:1 on the panel surface and
    is unusable; status error is #e2685c (5.06:1 on panel) instead.
  - terracotta #c96442 measures 4.28:1 as *text* on panel, so accent text uses
    the lighter coral #e08e6d (5.35:1). Terracotta remains the fill colour, and
    takes near-black text at 4.73:1.
  - stone #87867f measures 3.62:1 on the elevated surface, so it is
    DECORATION ONLY and must never carry body text or an essential label.
"""

from __future__ import annotations

from typing import cast

# ─── Tokens ─────────────────────────────────────────────────────────────────
#
# Structured as nested groups. build_css() reads them through typed helpers
# below rather than raw subscripts, so the emitter stays honest if a group is
# renamed or a value is dropped.

SURFACE: dict[str, str] = {
    "base": "#141413",      # Anthropic Near Black — app canvas
    "panel": "#1e1e1c",     # warm step up, keeps the olive undertone
    "elevated": "#30302e",  # Dark Surface — cards, popovers
    "overlay": "#383835",   # menus, dialogs
    # Hairlines: warm, not white. Claude's Border Cream at low alpha.
    "line": "rgba(176,174,165,0.16)",
    "line_strong": "rgba(176,174,165,0.30)",
}

TEXT: dict[str, str] = {
    "primary": "#faf9f5",   # Ivory — 17.5:1 on base
    "secondary": "#b0aea5",  # Warm Silver — 8.29:1 on base, 5.95:1 on elevated
    "muted": "#87867f",     # Stone — 5.04:1 on base, DECORATION ONLY
    "inverse": "#141413",   # on an accent fill
}

ACCENT: dict[str, str] = {
    "base": "#c96442",      # Terracotta — fills, rails, borders ONLY
    "text": "#e08e6d",      # lighter coral for accent-coloured TEXT
    "hover": "#d97757",
    "pressed": "#b5543a",
    "quiet": "rgba(201,100,66,0.14)",
}

STATUS: dict[str, str] = {
    "live": "#2a9d8f",      # teal-green: reads as state, never as brand
    "idle": "#87867f",
    "warn": "#e9b44c",      # muted amber, not a saturated red
    "error": "#e2685c",
    "info": "#7ba0c8",      # the one cool value; a non-brand semantic
}

TYPE: dict[str, object] = {
    "sans": "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    "scale": {
        "micro": 11, "caption": 12, "body": 14, "subhead": 16,
        "title": 20, "display": 28, "hero": 40,
    },
    # Apple tracks tight at EVERY size, not just display sizes.
    "tracking": {"tight": "-0.028em", "snug": "-0.020em", "label": "0.08em"},
    "leading": {"tight": 1.10, "body": 1.47},
    "weight": {"regular": 400, "medium": 500, "semibold": 600, "bold": 700},
}

SPACE: dict[str, str] = {
    "1": "4px", "2": "8px", "3": "12px", "4": "16px",
    "5": "20px", "6": "24px", "8": "32px", "10": "40px", "12": "48px",
}

RADIUS: dict[str, str] = {
    "sm": "5px", "md": "8px", "lg": "12px", "pill": "980px", "circle": "50%",
}

ELEVATION: dict[str, str] = {
    "flat": "none",
    "ring": "0 0 0 1px rgba(176,174,165,0.16)",
    "ring_accent": "0 0 0 1px rgba(201,100,66,0.55)",
    "whisper": "0 4px 24px rgba(0,0,0,0.28)",
}

MOTION: dict[str, str] = {
    "fast": "150ms cubic-bezier(0.16, 1, 0.3, 1)",
    "normal": "250ms cubic-bezier(0.16, 1, 0.3, 1)",
}

RAIL_WIDTH = "200px"
RAIL_WIDTH_COMPACT = "56px"

THEME: dict[str, object] = {
    "surface": SURFACE,
    "text": TEXT,
    "accent": ACCENT,
    "status": STATUS,
    "type": TYPE,
    "space": SPACE,
    "radius": RADIUS,
    "elevation": ELEVATION,
    "motion": MOTION,
    "rail_width": RAIL_WIDTH,
    "rail_width_compact": RAIL_WIDTH_COMPACT,
}

# Measured WCAG 2.1 contrast for every text-bearing pair. Re-verify with
# `python -m uartscope_theme --audit` if any value below changes.
CONTRAST_AUDIT: list[tuple[str, str, str, float, str]] = [
    # (label, foreground, background, ratio, verdict)
    ("text-primary on base",      "#faf9f5", "#141413", 17.50, "AAA"),
    ("text-primary on panel",     "#faf9f5", "#1e1e1c", 15.85, "AAA"),
    ("text-primary on elevated",  "#faf9f5", "#30302e", 12.55, "AAA"),
    ("text-secondary on base",    "#b0aea5", "#141413",  8.29, "AAA"),
    ("text-secondary on panel",   "#b0aea5", "#1e1e1c",  7.51, "AAA"),
    ("text-secondary on elevated","#b0aea5", "#30302e",  5.95, "AA"),
    ("accent text on base",       "#e08e6d", "#141413",  7.25, "AAA"),
    ("accent text on panel",      "#e08e6d", "#1e1e1c",  6.57, "AA"),
    ("accent text on elevated",   "#e08e6d", "#30302e",  5.20, "AA"),
    ("status live on base",       "#2a9d8f", "#141413",  5.55, "AA"),
    ("status live on panel",      "#2a9d8f", "#1e1e1c",  5.02, "AA"),
    ("status warn on base",       "#e9b44c", "#141413",  9.74, "AAA"),
    ("status warn on panel",      "#e9b44c", "#1e1e1c",  8.82, "AAA"),
    ("status error on base",      "#e2685c", "#141413",  5.59, "AA"),
    ("status error on panel",     "#e2685c", "#1e1e1c",  5.06, "AA"),
    ("status info on base",       "#7ba0c8", "#141413",  6.76, "AA"),
    ("status info on panel",      "#7ba0c8", "#1e1e1c",  6.13, "AA"),
    ("inverse text on accent",    "#141413", "#c96442",  4.73, "AA"),
    ("text-primary on error",     "#faf9f5", "#e2685c",  3.13, "AA-large"),
    # Error is a LIGHT fill, so it takes dark text, not ivory:
    ("inverse text on error",     "#141413", "#e2685c",  5.59, "AA"),
    # Decoration only — never body text:
    ("muted on base (decor)",     "#87867f", "#141413",  5.04, "AA"),
    ("muted on elevated (decor)", "#87867f", "#30302e",  3.62, "AA-large"),
]


# ─── Icons ──────────────────────────────────────────────────────────────────
# Inline SVG, stroke=currentColor, 1.5px, 20x20 viewBox. Replaces the unicode
# glyphs (◈ ▸ ◇ ⚡ ☁ ◉ ⟳ ⬡ 🛒) whose rendering varies by platform font.
# Chosen for even optical weight at 20px; all share the same 24-unit grid.

ICONS: dict[str, str] = {
    "devices": (
        '<rect x="2.5" y="4.5" width="19" height="13" rx="2"/>'
        '<path d="M8 20.5h8M12 17.5v3"/>'
    ),
    "terminal": (
        '<rect x="2.5" y="4.5" width="19" height="15" rx="2"/>'
        '<path d="M6.5 10l3 3-3 3M12.5 16h5"/>'
    ),
    "charts": (
        '<path d="M3 20.5h18"/>'
        '<path d="M5.5 16.5v-5M10 16.5V6.5M14.5 16.5v-8M19 16.5V9"/>'
    ),
    "performance": (
        '<path d="M13.5 2.5L5 13.5h6l-.5 8L19 10.5h-6l.5-8z"/>'
    ),
    "mqtt": (
        '<path d="M6.5 17.5a4.5 4.5 0 014.5-4.5h5"/>'
        '<path d="M6.5 12.5a8.5 8.5 0 018.5 8.5"/>'
        '<path d="M6.5 7.5a12.5 12.5 0 0112.5 12.5"/>'
        '<circle cx="6" cy="18" r="1.6" fill="currentColor" stroke="none"/>'
    ),
    "alerts": (
        '<path d="M12 3.5l8.5 15h-17l8.5-15z"/>'
        '<path d="M12 9.5v4.5M12 17h.01"/>'
    ),
    "sessions": (
        '<path d="M3.5 12a8.5 8.5 0 108.5-8.5c-2.2 0-4.2.8-5.8 2.2"/>'
        '<path d="M3.5 3.5v4h4"/>'
        '<path d="M12 8v4.5l3 1.8"/>'
    ),
    # Decoder: show the TRANSFORMATION (raw -> structured), not a generic chip.
    # A chip icon reads as "hardware" and says nothing about decoding.
    "decoder": (
        '<path d="M3.5 6.5h6M3.5 6.5v5M3.5 6.5h3.5l3 5h-3.5"/>'
        '<path d="M13 6.5h7.5M13 17.5h7.5M18 4.5v4M18 15.5v4"/>'
    ),
    "marketplace": (
        '<path d="M3.5 6.5h17l-1.5 11h-14l-1.5-11z"/>'
        '<path d="M8.5 9.5V6a3.5 3.5 0 017 0v3.5"/>'
    ),
}


def icon(name: str, size: int = 20, cls: str = "") -> str:
    """Return an inline SVG string for `name` (see ICONS).

    Icons inherit colour via currentColor so a single CSS rule themes them.
    aria-hidden: the adjacent text label is the accessible name.
    """
    if name not in ICONS:
        raise KeyError(f"unknown icon {name!r}; have: {sorted(ICONS)}")
    classes = f' class="{cls}"' if cls else ""
    return (
        f'<svg{classes} width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{ICONS[name]}</svg>"
    )


# ─── Contrast utilities ─────────────────────────────────────────────────────

def _srgb_to_linear(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colours."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def verify_contrast() -> list[str]:
    """Return a list of contrast failures. Empty list means the palette holds."""
    failures = []
    for label, fg, bg, recorded, _verdict in CONTRAST_AUDIT:
        actual = contrast_ratio(fg, bg)
        if abs(actual - recorded) > 0.02:
            failures.append(
                f"{label}: recorded {recorded:.2f} but computes {actual:.2f}")
    return failures


# ─── CSS emitter ────────────────────────────────────────────────────────────

def build_css() -> str:
    """Emit the semantic stylesheet.

    Screens reference these class names (us-*) and never raw values, so the
    palette can change in exactly one place.
    """
    s, x, a, st = SURFACE, TEXT, ACCENT, STATUS
    tracking = cast(dict, TYPE["tracking"])
    leading = cast(dict, TYPE["leading"])
    weight = cast(dict, TYPE["weight"])
    sp, r, e, mo = SPACE, RADIUS, ELEVATION, MOTION

    def type_rule(size: str, w: str, track: str, lead: str,
                  color: str, mono: bool = False) -> str:
        fam = cast(str, TYPE["mono"]) if mono else cast(str, TYPE["sans"])
        return (f"font-family:{fam};font-size:{size};font-weight:{w};"
                f"letter-spacing:{track};line-height:{lead};color:{color};")

    return f"""
/* ── UARTScope v2 theme ───────────────────────────────────────────────────
   Generated by uartscope_theme.build_css(). Do not edit the output.
   Apple discipline + Claude warm neutrals + terracotta accent.            */

*, *::before, *::after {{ box-sizing: border-box; }}

body, .q-body {{
  background: {s['base']};
  color: {x['primary']};
  {type_rule('14px', weight['regular'], tracking['snug'], leading['body'], x['primary'])}
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* ── Surfaces ────────────────────────────────────────────────────────────── */
.us-surface   {{ background:{s['base']}; }}
.us-panel     {{ background:{s['panel']}; }}
.us-elevated  {{ background:{s['elevated']}; }}
.us-overlay   {{ background:{s['overlay']}; }}
.us-line      {{ border:1px solid {s['line']}; }}
.us-line-accent {{ border:1px solid {a['quiet']}; }}

/* A card: no border, no drop shadow. Elevation is the surface step alone. */
.us-card {{
  background:{s['elevated']};
  border-radius:{r['lg']};
  padding:{sp['6']};
}}

/* ── Type ────────────────────────────────────────────────────────────────── */
.us-display {{ {type_rule('28px', weight['semibold'], tracking['tight'], leading['tight'], x['primary'])} }}
.us-title   {{ {type_rule('20px', weight['semibold'], tracking['snug'], leading['tight'], x['primary'])} }}
.us-subhead {{ {type_rule('16px', weight['medium'], tracking['snug'], '1.3', x['primary'])} }}
.us-body    {{ {type_rule('14px', weight['regular'], tracking['snug'], leading['body'], x['secondary'])} }}
.us-caption {{ {type_rule('12px', weight['regular'], '0', '1.29', x['secondary'])} }}
/* Label: the small uppercase run. Tracking is POSITIVE here — the one
   exception to Apple's tight-everywhere rule, because uppercase micro text
   needs the air. */
.us-label   {{ {type_rule('12px', weight['medium'], tracking['label'], '1.33', x['secondary'])}
               text-transform:uppercase; }}
.us-micro   {{ {type_rule('11px', weight['regular'], '0', '1.33', x['muted'])} }}
/* DECORATION ONLY — 3.62:1 on elevated. Never body text or an essential label. */
.us-muted   {{ color:{x['muted']}; }}
.us-accent-text {{ color:{a['text']}; }}
/* Numeric data: monospace, tabular figures so digits don't jitter as they update. */
.us-mono    {{ {type_rule('13px', weight['medium'], '0', '1.4', x['primary'], mono=True)}
               font-variant-numeric:tabular-nums; }}
.us-metric  {{ {type_rule('24px', weight['semibold'], tracking['tight'], '1.1', x['primary'], mono=True)}
               font-variant-numeric:tabular-nums; }}

/* ── Status ──────────────────────────────────────────────────────────────── */
/* Indicators (dots, rules, text) — never a fill that carries light text. */
.us-live  {{ color:{st['live']}; }}
.us-idle  {{ color:{st['idle']}; }}
.us-warn  {{ color:{st['warn']}; }}
.us-error {{ color:{st['error']}; }}
.us-info  {{ color:{st['info']}; }}
.us-dot {{
  width:7px; height:7px; border-radius:{r['circle']};
  background:currentColor; flex:0 0 auto; display:inline-block;
}}
.us-dot-live {{ background:{st['live']}; }}
.us-dot-idle {{ background:{st['idle']}; }}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.us-btn {{
  display:inline-flex; align-items:center; gap:{sp['2']};
  font-family:{TYPE['sans']}; font-size:14px; font-weight:{weight['medium']};
  letter-spacing:{tracking['snug']};
  padding:8px 16px; border-radius:{r['md']};
  border:1px solid transparent; cursor:pointer;
  transition:background {mo['fast']}, color {mo['fast']}, border-color {mo['fast']};
  min-height:36px;
}}
/* Primary: the only chromatic fill in the interface. Near-black text at 4.73:1. */
.us-btn-primary {{ background:{a['base']}; color:{x['inverse']}; }}
.us-btn-primary:hover {{ background:{a['hover']}; }}
.us-btn-primary:active {{ background:{a['pressed']}; }}
/* Secondary: warm sand, ring shadow rather than a drop shadow. */
.us-btn-secondary {{
  background:{s['elevated']}; color:{x['primary']};
  box-shadow:{e['ring']};
}}
.us-btn-secondary:hover {{ background:{s['overlay']}; }}
/* Ghost: text-only, for tertiary actions. */
.us-btn-ghost {{ background:transparent; color:{x['secondary']}; }}
.us-btn-ghost:hover {{ background:rgba(176,174,165,0.10); color:{x['primary']}; }}
.us-btn-danger {{ background:transparent; color:{st['error']};
                  box-shadow:{e['ring']}; }}
.us-btn-danger:hover {{ background:rgba(226,104,92,0.14); }}
.us-btn:disabled, .us-btn[aria-disabled="true"] {{
  opacity:0.45; cursor:not-allowed; pointer-events:none;
}}

/* ── Inputs ──────────────────────────────────────────────────────────────── */
.us-input {{
  background:{s['panel']}; color:{x['primary']};
  border:1px solid {s['line_strong']}; border-radius:{r['md']};
  padding:8px 12px; min-height:36px; width:100%;
  font-family:{TYPE['sans']}; font-size:14px;
  transition:border-color {mo['fast']};
}}
.us-input::placeholder {{ color:{x['muted']}; opacity:1; }}
.us-input:hover {{ border-color:rgba(176,174,165,0.42); }}
/* The focus ring is a real 2px terracotta outline. v1 suppressed focus on every
   form control and left only a border-colour swap. */
.us-input:focus, .us-input:focus-visible {{
  outline:2px solid {a['base']}; outline-offset:2px; border-color:transparent;
}}

/* ── Focus, everywhere ───────────────────────────────────────────────────── */
.us-focusable:focus-visible, .q-btn:focus-visible, .q-item:focus-visible {{
  outline:2px solid {a['base']}; outline-offset:2px; border-radius:{r['sm']};
}}

/* ── Navigation ──────────────────────────────────────────────────────────── */
.us-rail {{ background:{s['panel']}; border-right:1px solid {s['line']};
            width:{RAIL_WIDTH}; }}
.us-rail-item {{
  display:flex; align-items:center; gap:{sp['3']};
  width:100%; padding:10px 12px; border-radius:{r['md']};
  color:{x['secondary']}; font-size:14px; font-weight:{weight['regular']};
  letter-spacing:{tracking['snug']};
  border:none; background:transparent; cursor:pointer; text-align:left;
  position:relative; min-height:40px;
  transition:background {mo['fast']}, color {mo['fast']};
}}
.us-rail-item:hover {{ background:rgba(176,174,165,0.08); color:{x['primary']}; }}
/* Active state carries THREE signals, not colour alone: a terracotta rail, a
   weight bump, and aria-current. Colour-only is not an accessible state. */
.us-rail-item[aria-current="page"] {{
  background:{a['quiet']}; color:{x['primary']}; font-weight:{weight['medium']};
}}
.us-rail-item[aria-current="page"]::before {{
  content:''; position:absolute; left:0; top:50%; transform:translateY(-50%);
  width:3px; height:20px; border-radius:0 2px 2px 0; background:{a['base']};
}}
.us-rail-item[aria-current="page"] svg {{ color:{a['text']}; }}
/* Below 1024px the rail collapses to icons — but the accessible name stays,
   because the label is real text, not a title attribute. */
@media (max-width: 1024px) {{
  .us-rail {{ width:{RAIL_WIDTH_COMPACT}; }}
  .us-rail-label {{ display:none; }}
  .us-rail-item {{ justify-content:center; padding:10px 0; }}
}}

/* ── Header ──────────────────────────────────────────────────────────────── */
.us-header {{
  display:flex; align-items:center; justify-content:space-between; gap:{sp['4']};
  padding:{sp['4']} {sp['6']};
  border-bottom:1px solid {s['line']};
  background:{s['base']};
  position:sticky; top:0; z-index:10;
}}
.us-status {{
  display:inline-flex; align-items:center; gap:{sp['2']};
  padding:5px 12px; border-radius:{r['pill']};
  box-shadow:{e['ring']}; background:{s['panel']};
}}

/* ── Empty state ─────────────────────────────────────────────────────────── */
/* An empty state is a dead end unless it offers the next action. */
.us-empty {{
  display:flex; flex-direction:column; align-items:flex-start; gap:{sp['4']};
  padding:{sp['10']}; border-radius:{r['lg']}; background:{s['panel']};
  box-shadow:{e['ring']};
}}
.us-empty-steps {{ display:flex; flex-direction:column; gap:{sp['3']};
                   margin:0; padding:0; list-style:none; }}
.us-empty-step {{ display:flex; gap:{sp['3']}; align-items:flex-start;
                  font-size:14px; color:{x['secondary']}; }}
.us-step-num {{
  flex:0 0 auto; width:20px; height:20px; border-radius:{r['circle']};
  display:inline-flex; align-items:center; justify-content:center;
  background:{a['quiet']}; color:{a['text']};
  font-size:11px; font-weight:{weight['semibold']};
}}

/* ── Data rows (Operate surfaces) ────────────────────────────────────────── */
.us-row {{
  display:flex; align-items:center; gap:{sp['3']};
  padding:10px 12px; border-radius:{r['md']};
  background:{s['elevated']}; min-height:44px;
  transition:background {mo['fast']};
}}
.us-row:hover {{ background:{s['overlay']}; }}

/* ── Motion ──────────────────────────────────────────────────────────────── */
@keyframes us-pulse {{
  0%,100% {{ opacity:1; }} 50% {{ opacity:0.45; }}
}}
.us-pulse {{ animation:us-pulse 2.4s ease-in-out infinite; }}
@keyframes us-fade {{ from {{ opacity:0; }} to {{ opacity:1; }} }}
.us-fade {{ animation:us-fade {mo['normal']}; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration:0.01ms !important; animation-iteration-count:1 !important;
    transition-duration:0.01ms !important; scroll-behavior:auto !important;
  }}
}}

/* ── Scrollbars ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width:8px; height:8px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
::-webkit-scrollbar-thumb {{ background:rgba(176,174,165,0.22);
                            border-radius:{r['pill']}; }}
::-webkit-scrollbar-thumb:hover {{ background:rgba(176,174,165,0.38); }}

/* ── Selection ───────────────────────────────────────────────────────────── */
::selection {{ background:{a['quiet']}; color:{x['primary']}; }}
"""


def inject_theme_css(ui) -> None:
    """Attach the v2 stylesheet and the Inter/JetBrains Mono faces to the page.

    Call once, before any screen is built. Fonts load from a CDN with a
    system-ui fallback, so the app still renders correctly offline.
    """
    ui.add_css(build_css())
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2'
        '?family=Inter:wght@400;500;600;700'
        '&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
    )


# ─── Self-audit ─────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--audit" in sys.argv:
        print(f"{'pair':30s} {'ratio':>6s}  verdict")
        print("-" * 56)
        bad = []
        for label, fg, bg, recorded, verdict in CONTRAST_AUDIT:
            actual = contrast_ratio(fg, bg)
            mark = "ok" if abs(actual - recorded) <= 0.02 else "DRIFT"
            print(f"{label:30s} {actual:6.2f}  {verdict} ({mark})")
            if mark == "DRIFT":
                bad.append(label)
        print()
        if bad or verify_contrast():
            print("FAIL:", bad or verify_contrast())
            sys.exit(1)
        print(f"all {len(CONTRAST_AUDIT)} pairs hold")
    else:
        css = build_css()
        print(f"{len(css)} chars of CSS, {len(ICONS)} icons, "
              f"{len(THEME)} token groups")
