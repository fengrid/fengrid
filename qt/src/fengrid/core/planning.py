"""Planning core: the Kanban task model behind the Planning pane (#132).

Tasks are first-class rows in ``project_task`` — optionally assigned to a
project and optionally linked to library assets (``project_task_asset``,
same shape as ``project_asset``). Stage progression is a Kanban move:
``move_task`` re-seats a task inside its new stage using fractional
positions (midpoint between neighbours), so reordering never rewrites
the whole column.

Stage keys are stable identifiers (stored in the DB); labels and colors
live here so QML and tests agree on them.
"""

from __future__ import annotations

import re
import sqlite3
import uuid

from . import db as core_db

# (key, label, dark dot hex, light dot hex) — order is the board order.
# Hues follow the reference board in #132 (GitHub-style status colors),
# darkened on the light surface for contrast.
STAGES: tuple[tuple[str, str, str, str], ...] = (
    ("triage", "Triage", "#E6EDF3", "#24292F"),
    ("todo", "ToDo", "#8B949E", "#57606A"),
    ("scheduled", "Scheduled", "#A371F7", "#8250C8"),
    ("ready", "Ready", "#4493F8", "#0A63C9"),
    ("running", "Running", "#3FB950", "#1A7F37"),
    ("blocked", "Blocked", "#F85149", "#C93C37"),
    ("review", "Review", "#D29922", "#9A6700"),
    ("done", "Done", "#8B949E", "#57606A"),
)
STAGE_KEYS = tuple(s[0] for s in STAGES)
STAGE_LABELS = {s[0]: s[1] for s in STAGES}

PRIORITIES = ("", "low", "normal", "high")

_POSITION_STEP = 1.0
_GUID_RE = re.compile(r"^[0-9a-f]{8}$")


def new_guid() -> str:
    return uuid.uuid4().hex[:8]


def migrate(con: sqlite3.Connection) -> None:
    """The tables are in SCHEMA (CREATE IF NOT EXISTS) — this heals any
    pre-schema databases and backfills nothing by design (tasks are new)."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(project_task)")}
    if not cols:
        return
    if "due_date" not in cols:
        con.execute("ALTER TABLE project_task ADD COLUMN due_date TEXT"
                    " NOT NULL DEFAULT ''")
    if "status_note" not in cols:
        con.execute("ALTER TABLE project_task ADD COLUMN status_note"
                    " TEXT NOT NULL DEFAULT ''")
    con.commit()


# --------------------------------------------------------------------- read


def stages(con: sqlite3.Connection) -> list[dict]:
    # "name" mirrors "label" so QML ComboBox textRole works uniformly
    return [{"key": k, "label": lab, "name": lab, "dark": d, "light": l}
            for k, lab, d, l in STAGES]


def _task_row(con, r) -> dict:
    t = dict(r)
    t["projectName"] = ""
    if t.get("project_id"):
        prow = con.execute("SELECT name FROM projects WHERE id = ?",
                           (t["project_id"],)).fetchone()
        t["projectName"] = prow["name"] if prow else ""
    n = con.execute("SELECT COUNT(*) FROM project_task_asset"
                    " WHERE task_id = ?", (t["id"],)).fetchone()[0]
    t["assetCount"] = int(n)
    t["shortId"] = (t.get("guid") or "")[:6]
    return t


def board(con: sqlite3.Connection, search: str = "") -> list[dict]:
    """Every stage with its cards (position-ordered). ``search`` filters
    by title/description/project name — empty stages stay visible."""
    q = ""
    args: list = []
    if search.strip():
        q = ("AND (t.title LIKE ? OR t.description LIKE ?"
             " OR p.name LIKE ?)")
        like = f"%{search.strip()}%"
        args = [like, like, like]
    out = []
    for key, label, dark, light in STAGES:
        rows = con.execute(
            "SELECT t.* FROM project_task t"
            " LEFT JOIN projects p ON p.id = t.project_id"
            f" WHERE t.stage = ? {q}"
            " ORDER BY t.position, t.id", (key, *args)).fetchall()
        out.append({"key": key, "label": label, "dark": dark,
                    "light": light,
                    "cards": [_task_row(con, r) for r in rows]})
    return out


def counts(con: sqlite3.Connection) -> dict[str, int]:
    return {r["stage"]: int(r["n"]) for r in con.execute(
        "SELECT stage, COUNT(*) AS n FROM project_task GROUP BY stage")}


def total(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM project_task"
                           ).fetchone()[0])


def task(con: sqlite3.Connection, task_id: int) -> dict | None:
    r = con.execute("SELECT * FROM project_task WHERE id = ?",
                    (int(task_id),)).fetchone()
    if r is None:
        return None
    t = _task_row(con, r)
    t["assets"] = [dict(a) for a in con.execute(
        "SELECT id, asset_kind AS assetKind, asset_id AS assetId,"
        " label FROM project_task_asset WHERE task_id = ?"
        " ORDER BY id", (int(task_id),))]
    for a in t["assets"]:
        a["name"] = _asset_name(con, a["assetKind"], a["assetId"])
    return t


def _asset_name(con, kind: str, asset_id: int) -> str:
    if kind == "snippet":
        row = con.execute("SELECT title FROM snippet WHERE id = ?",
                          (asset_id,)).fetchone()
        return row["title"] if row else f"#{asset_id}"
    if kind == "palette":
        row = con.execute("SELECT name FROM palette WHERE id = ?",
                          (asset_id,)).fetchone()
        return row["name"] if row else f"#{asset_id}"
    row = con.execute("SELECT name, family FROM asset WHERE id = ?",
                      (asset_id,)).fetchone()
    if row is None:
        return f"#{asset_id}"
    return (row["family"] + " · " + row["name"]) if row["family"] \
        else row["name"]


def project_options(con: sqlite3.Connection) -> list[dict]:
    return [{"id": r["id"], "name": r["name"]} for r in con.execute(
        "SELECT id, name FROM projects ORDER BY name COLLATE NOCASE")]


def asset_options(con: sqlite3.Connection, kind: str) -> list[dict]:
    if kind == "snippet":
        rows = con.execute("SELECT id, title FROM snippet"
                           " ORDER BY title LIMIT 500").fetchall()
        return [{"id": r["id"], "name": r["title"]} for r in rows]
    if kind == "palette":
        rows = con.execute("SELECT id, name FROM palette"
                           " ORDER BY name LIMIT 500").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    if kind not in ("icon", "font"):
        return []
    rows = con.execute("SELECT id, name, family FROM asset"
                       " WHERE kind = ? ORDER BY name LIMIT 500",
                       (kind,)).fetchall()
    return [{"id": r["id"], "name": (r["family"] + " · " + r["name"])
             if r["family"] else r["name"]} for r in rows]


# -------------------------------------------------------------------- write


def _next_position(con: sqlite3.Connection, stage: str) -> float:
    row = con.execute("SELECT MAX(position) FROM project_task"
                      " WHERE stage = ?", (stage,)).fetchone()
    return (row[0] or 0.0) + _POSITION_STEP


def create_task(con: sqlite3.Connection, title: str, stage: str = "triage",
                project_id: int | None = None, description: str = "",
                priority: str = "", due_date: str = "") -> int:
    if stage not in STAGE_KEYS:
        stage = "triage"
    cur = con.execute(
        "INSERT INTO project_task(title, description, stage, position,"
        " project_id, priority, due_date, guid, slug)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title.strip() or "Untitled task", description.strip(),
         stage, _next_position(con, stage),
         int(project_id) if project_id else None,  # type: ignore[arg-type]
         priority if priority in PRIORITIES else "",
         due_date.strip(), new_guid(), ""))
    con.commit()
    return int(cur.lastrowid)


def update_task(con: sqlite3.Connection, task_id: int, **fields) -> bool:
    """Whitelisted field writes; stage changes go through move_task so
    ordering stays consistent."""
    allowed = {"title", "description", "status_note", "due_date",
               "priority", "project_id"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "priority" and v not in PRIORITIES:
            continue
        if k == "project_id":
            v = int(v) if v else None
        sets.append(f"{k} = ?")
        args.append(v)
    if not sets:
        return False
    sets.append("updated = datetime('now')")
    args.append(int(task_id))
    con.execute(f"UPDATE project_task SET {', '.join(sets)} WHERE id = ?",
                args)
    con.commit()
    return True


def move_task(con: sqlite3.Connection, task_id: int, stage: str,
              index: int) -> bool:
    """Move to ``stage`` at ``index`` (0-based within the stage, clamped
    to the current length). Fractional midpoint keeps siblings stable."""
    if stage not in STAGE_KEYS:
        return False
    row = con.execute("SELECT stage FROM project_task WHERE id = ?",
                      (int(task_id),)).fetchone()
    if row is None:
        return False
    siblings = [r["id"] for r in con.execute(
        "SELECT id FROM project_task WHERE stage = ? AND id != ?"
        " ORDER BY position, id", (stage, int(task_id)))]
    index = max(0, min(int(index), len(siblings)))
    lo = con.execute("SELECT position FROM project_task WHERE id = ?",
                     (siblings[index - 1],)).fetchone()[0] \
        if index > 0 else 0.0
    hi = con.execute("SELECT position FROM project_task WHERE id = ?",
                     (siblings[index],)).fetchone()[0] \
        if index < len(siblings) else (lo + 2 * _POSITION_STEP)
    con.execute(
        "UPDATE project_task SET stage = ?, position = ?,"
        " updated = datetime('now') WHERE id = ?",
        (stage, (lo + hi) / 2.0, int(task_id)))
    con.commit()
    return True


def delete_task(con: sqlite3.Connection, task_id: int) -> None:
    con.execute("DELETE FROM project_task WHERE id = ?", (int(task_id),))
    con.commit()


def link_asset(con: sqlite3.Connection, task_id: int, kind: str,
               asset_id: int, label: str = "") -> bool:
    if kind not in ("icon", "font", "snippet", "palette"):
        return False
    exists = _asset_name(con, kind, int(asset_id))
    if exists.startswith("#") and exists == f"#{int(asset_id)}":
        return False
    con.execute(
        "INSERT OR IGNORE INTO project_task_asset(task_id, asset_kind,"
        " asset_id, label) VALUES (?, ?, ?, ?)",
        (int(task_id), kind, int(asset_id), label.strip()))
    con.commit()
    return True


def unlink_asset(con: sqlite3.Connection, row_id: int) -> None:
    con.execute("DELETE FROM project_task_asset WHERE id = ?",
                (int(row_id),))
    con.commit()


def open_by_title(con: sqlite3.Connection, needle: str) -> int:
    """QA hook: the first task whose title contains ``needle``."""
    row = con.execute(
        "SELECT id FROM project_task WHERE title LIKE ? ORDER BY id",
        (f"%{needle}%",)).fetchone()
    return int(row["id"]) if row else -1


# connection hygiene for worker-owned use is inherited from core_db
connect = core_db.connect
