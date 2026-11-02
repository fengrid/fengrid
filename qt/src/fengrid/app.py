"""Application metadata and brand tokens shared by the QML shell.

Token values come from the shared pane design system and the brand identity
(docs/review/2026-current-state-review.md §1.2, branding/fengrid-brand.md).
At M0 (docs/architecture/0001-qt6-rewrite.md §10) the authoritative set is
re-extracted from the pane CSS into this module — one source of truth for
QML thereafter.
"""

APP_NAME = "Fengrid"
ORG_NAME = "Native IT"
VERSION = "0.3.0.dev0"

# Brand tokens (dark theme is primary).
DARK = {
    "bg": "#101418",
    "surface": "#161B21",
    "surface2": "#1D242B",
    "border": "#2A333B",
    "text": "#E7EDF2",
    "text_muted": "#6E7B86",
    # translucent scrims for hover overlays on color chips (see LIGHT)
    "scrim": "#40000000",
    "scrim_soft": "#25000000",
    "accent": "#39B8C4",   # teal — pane outlines, active states
    "lit_pane": "#F5C25C",  # amber — the lit asset, selection highlights
    "success": "#5BB98B",
    # per-category accents (0.x pane colors): Icons teal, Fonts violet,
    # Code coral, Colors rose, Projects green
    "accent_icon": "#39B8C4",
    "accent_font": "#A78BFA",
    "accent_code": "#F0885C",
    "accent_color": "#E879A6",
    "accent_project": "#63C48B",
    "accent_planning": "#5AA7E8",   # Planning pane — board blue (distinct
                                    # from the other five category hues)
    # syntax-highlight tokens (code pane); values from the 0.x pane CSS
    "hl_ink": "#F5C25C",    # attributes / CSS props / numbers
    "ink_faint": "#7E8B96",   # comment/placeholder ink (code pane) —
                              # 4.87:1 on the editor surface #161B21;
                              # the old #5F6C78 was 3.16:1, too faint
}

# Light theme (secondary); surface2 derived from the brand palette sheet.
LIGHT = {
    "bg": "#F7F8F9",
    "surface": "#FFFFFF",
    "surface2": "#EEF1F3",
    "border": "#D5DCE0",
    "text": "#16202B",
    # A11Y-4: 4.97:1 on surface2 (#EEF1F3) — the old #6B7A88 was 3.9:1,
    # below AA for small text
    "text_muted": "#5A6977",
    # translucent scrims for hover overlays on color chips (theme tokens,
    # replacing Colors.qml's hardcoded #40000000/#25000000 — lighter on
    # the light theme so swatches stay readable)
    "scrim": "#26000000",
    "scrim_soft": "#13000000",
    "accent": "#0E7C86",
    "lit_pane": "#F5B841",
    "success": "#2E7D4F",
    # per-category accents, darkened for the light surface (contrast)
    "accent_icon": "#0E7C86",
    "accent_font": "#6D4FC4",
    "accent_code": "#C44A1E",
    "accent_color": "#B0306A",
    "accent_project": "#1B7A4E",
    "accent_planning": "#1D6FD6",   # darkened for the light surface
    "hl_ink": "#A16207",    # raw amber on white is 1.78:1 — use the ink tone
    "ink_faint": "#9AA6B0",
}

# Accent presets for the Settings "Accent color" row and the first-run
# picker — Fengrid's own palette ids (the 0.x pane accents + the amber
# lit-pane), each with a light-surface variant that keeps ≥4.5:1 text
# contrast. `accent` picks the *dark*-theme value; the light theme uses
# the second slot. The default is the brand teal.
ACCENTS = {
    "teal":   ("Teal",   "#39B8C4", "#0E7C86"),
    "amber":  ("Amber",  "#F5C25C", "#B07E12"),
    "violet": ("Violet", "#A78BFA", "#7C5CD6"),
    "coral":  ("Coral",  "#F0885C", "#C0561F"),
    "rose":   ("Rose",   "#E879A6", "#C0437B"),
    "green":  ("Green",  "#63C48B", "#2E8B57"),
}
