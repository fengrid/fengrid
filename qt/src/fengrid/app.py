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
    "accent": "#39B8C4",   # teal — pane outlines, active states
    "lit_pane": "#F5C25C",  # amber — the lit asset, selection highlights
}

# Light theme (secondary); surface2 derived from the brand palette sheet.
LIGHT = {
    "bg": "#F7F8F9",
    "surface": "#FFFFFF",
    "surface2": "#EEF1F3",
    "border": "#D5DCE0",
    "text": "#16202B",
    "text_muted": "#6B7A88",
    "accent": "#0E7C86",
    "lit_pane": "#F5B841",
}
