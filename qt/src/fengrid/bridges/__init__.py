"""Qt bridges: thin QObject adapters exposing core/ to QML.

Bridges own no business logic — they translate QML calls into core calls
and core data into models/properties (docs/architecture/0001-qt6-rewrite.md
§7).
"""
