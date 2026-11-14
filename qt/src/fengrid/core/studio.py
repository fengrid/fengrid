"""Studio core: the Projects pane's design/product model.

The reworked Projects pane ("Studio") is a multi-screen workspace:
Design (block canvas), Theme (token configurator), Code, Assets,
Revisions, Templates, Docker, Package, Docs. This module owns the DATA:

  - studio_page      — per-project pages, each a JSON block tree
  - block operations — add/move/remove/patch on that tree
  - rendering        — blocks -> HTML, resolving [[ asset ]] refs into
                       fengrid-asset:// urls and reusing the token
                       generator the exporter uses (one source of truth)
  - templates        — a project can be a TEMPLATE; instances are new
                       projects that share its pages with {{var}}
                       substitution (tenant/multi-implementation support)
  - characterization — asset-usage/link stats for the Docs screen

Design rules:
  - pages are small JSON trees; the DB stores one row per page, not one
    per block (blocks are cheap to rewrite wholesale)
  - block ids are stable within a page: props edits never reorder the
    tree, so undo/redo and the canvas selection survive edits
  - everything the renderer emits must be safe for the sandboxed
    preview: [[ refs ]] resolve ONLY through assetrefs.resolve()
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from . import assetrefs
from . import db as core_db

# block types the canvas offers (inspector renders per-type props)
BLOCK_TYPES = (
    "section", "text", "heading", "image", "button", "icon",
    "palette", "font", "snippet", "html", "spacer", "grid",
)

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")


class StudioError(Exception):
    """User-scale studio error (bad payload, unknown page/block…)."""


# ──────────────────────────────────────────────────────────────── schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS studio_page (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'page',   -- 'page' | 'component'
    sort       INTEGER NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL DEFAULT '[]',     -- JSON block tree (list)
    created    TEXT NOT NULL DEFAULT (datetime('now')),
    updated    TEXT NOT NULL DEFAULT (datetime('now')),
    guid       TEXT
);
"""


def migrate(con) -> None:
    con.executescript(SCHEMA)
    # guid column on legacy installs
    cols = {r[1] for r in con.execute("PRAGMA table_info(studio_page)")}
    if "guid" not in cols:
        con.execute("ALTER TABLE studio_page ADD COLUMN guid TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_studio_page_project"
                " ON studio_page(project_id, sort)")
    con.commit()


# ─────────────────────────────────────────────────────────── page CRUD
def list_pages(con, project_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT id, name, kind, sort, updated, guid FROM studio_page"
        " WHERE project_id = ? ORDER BY sort, id",
        (int(project_id),)).fetchall()
    return [dict(r) for r in rows]


def _project_exists(con, project_id: int) -> None:
    if con.execute("SELECT 1 FROM projects WHERE id = ?",
                   (int(project_id),)).fetchone() is None:
        raise StudioError(f"no project #{project_id}")


def create_page(con, project_id: int, name: str, kind: str = "page",
                payload: list | None = None) -> int:
    _project_exists(con, project_id)
    name = (name or "").strip()
    if not name:
        raise StudioError("page needs a name")
    if kind not in ("page", "component"):
        raise StudioError("kind must be page or component")
    if payload is None:
        payload = [_block("section", {"class": "hero"})]
    sort = con.execute(
        "SELECT COALESCE(MAX(sort), -1) + 1 FROM studio_page"
        " WHERE project_id = ?", (int(project_id),)).fetchone()[0]
    cur = con.execute(
        "INSERT INTO studio_page(project_id, name, kind, sort, payload,"
        " guid) VALUES (?,?,?,?,?,?)",
        (int(project_id), name, kind, sort, json.dumps(payload),
         core_db.new_guid()))
    con.commit()
    return cur.lastrowid


def get_page(con, page_id: int) -> dict | None:
    row = con.execute(
        "SELECT * FROM studio_page WHERE id = ?", (int(page_id),)).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d.get("payload") or "[]")
    except (ValueError, TypeError):
        d["payload"] = []
    return d


def rename_page(con, page_id: int, name: str) -> None:
    name = (name or "").strip()
    if not name:
        raise StudioError("page needs a name")
    con.execute("UPDATE studio_page SET name = ?, updated = ? WHERE id = ?",
                (name, _now(), int(page_id)))
    con.commit()


def delete_page(con, page_id: int) -> None:
    con.execute("DELETE FROM studio_page WHERE id = ?", (int(page_id),))
    con.commit()


def save_page(con, page_id: int, payload: list) -> dict:
    """Wholesale block-tree write (canvas commits). Returns the row."""
    _check_tree(payload)
    con.execute("UPDATE studio_page SET payload = ?, updated = ?"
                " WHERE id = ?",
                (json.dumps(payload), _now(), int(page_id)))
    con.commit()
    row = get_page(con, page_id)
    if row is None:                     # deleted mid-edit
        raise StudioError(f"no page #{page_id}")
    return row


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


# ─────────────────────────────────────────────────────────── block tree
def _block(btype: str, props: dict | None = None,
           children: list | None = None) -> dict:
    if btype not in BLOCK_TYPES:
        raise StudioError(f"unknown block type {btype!r}")
    return {
        "id": uuid.uuid4().hex[:8],
        "type": btype,
        "props": dict(props or {}),
        "children": list(children or []),
    }


def _check_tree(tree: Any, depth: int = 0) -> None:
    if depth > 12:
        raise StudioError("block tree too deep (recursion guard)")
    if not isinstance(tree, list):
        raise StudioError("payload must be a list of blocks")
    for b in tree:
        if not isinstance(b, dict):
            raise StudioError("blocks must be objects")
        if b.get("type") not in BLOCK_TYPES:
            raise StudioError(f"unknown block type {b.get('type')!r}")
        if not isinstance(b.get("props", {}), dict):
            raise StudioError("props must be an object")
        _check_tree(b.get("children", []), depth + 1)


def _walk(tree: list, block_id: str) -> tuple[list, int, dict] | None:
    """Depth-first find: returns (parent_list, index, block)."""
    for i, b in enumerate(tree):
        if b.get("id") == block_id:
            return tree, i, b
        hit = _walk(b.get("children", []), block_id)
        if hit:
            return hit
    return None


def add_block(page: dict, btype: str, props: dict | None = None,
              parent_id: str | None = None) -> dict:
    """Append a block — inside `parent_id` when given (container types:
    section/grid), else at the page root."""
    root = page["payload"]
    if parent_id:
        hit = _walk(root, parent_id)
        if hit is None:
            raise StudioError(f"no block {parent_id!r} on this page")
        parent = hit[2]
        if parent["type"] not in ("section", "grid"):
            raise StudioError(f"{parent['type']} blocks take no children")
        nb = _block(btype, props)
        parent["children"].append(nb)
    else:
        nb = _block(btype, props)
        root.append(nb)
    return nb


def move_block(page: dict, block_id: str, delta: int) -> None:
    hit = _walk(page["payload"], block_id)
    if hit is None:
        raise StudioError(f"no block {block_id!r}")
    lst, i, _ = hit
    j = i + int(delta)
    if not 0 <= j < len(lst):
        return                      # already at that edge — no-op
    lst[i], lst[j] = lst[j], lst[i]


def remove_block(page: dict, block_id: str) -> None:
    hit = _walk(page["payload"], block_id)
    if hit is None:
        raise StudioError(f"no block {block_id!r}")
    del hit[0][hit[1]]


def set_block_props(page: dict, block_id: str, props: dict) -> None:
    hit = _walk(page["payload"], block_id)
    if hit is None:
        raise StudioError(f"no block {block_id!r}")
    if not isinstance(props, dict):
        raise StudioError("props must be an object")
    hit[2]["props"] = dict(props)


def duplicate_block(page: dict, block_id: str) -> dict | None:
    """Copy a block (fresh id, same props) directly after it."""
    hit = _walk(page["payload"], block_id)
    if hit is None:
        return None
    lst, i, blk = hit
    import copy
    dup = copy.deepcopy(blk)
    dup["id"] = uuid.uuid4().hex[:8]

    def reid(node: dict) -> None:
        node["id"] = uuid.uuid4().hex[:8]
        for c in node.get("children", []):
            reid(c)
    reid(dup)
    lst.insert(i + 1, dup)
    return dup


# ──────────────────────────────────────────────────────── rendering
def render_blocks(con, blocks: list) -> str:
    """Block tree -> HTML fragment. [[ refs ]] resolve through
    assetrefs (fengrid-asset:// for files, expanded markup otherwise);
    unknown refs render as a visible placeholder, never raw."""
    out: list[str] = []
    for b in blocks:
        out.append(_render_block(con, b, depth=0))
    return "\n".join(out)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _ref(con, val: str, attr: str = "src") -> str:
    """Resolve a [[ ref ]] prop value; returns the attribute value."""
    hit = assetrefs.resolve(con, val)
    if hit:
        return assetrefs.url_for(hit)
    return _esc(val)


def _render_block(con, b: dict, depth: int) -> str:
    if depth > 12:
        return "<!-- depth limit -->"
    t = b["type"]
    p = b.get("props", {})
    kids = b.get("children", [])
    inner = "\n".join(_render_block(con, c, depth + 1) for c in kids)
    cls = _esc(p.get("class", ""))

    if t == "section":
        return f'<section class="{cls}">{inner}</section>'
    if t == "grid":
        cols = _esc(p.get("columns", 3))
        return (f'<div class="fg-grid" style="display:grid;'
                f'grid-template-columns:repeat({cols},1fr);gap:16px">'
                f"{inner}</div>")
    if t == "spacer":
        h = _esc(p.get("height", 24))
        return f'<div style="height:{h}px"></div>'
    if t == "text":
        return (f'<p class="{cls}">{_esc(p.get("text", ""))}</p>')
    if t == "heading":
        lvl = p.get("level", 2)
        if str(lvl) not in ("1", "2", "3", "4"):
            lvl = 2
        return (f'<h{lvl} class="{cls}">{_esc(p.get("text", ""))}'
                f"</h{lvl}>")
    if t == "image":
        src = _ref(con, p.get("ref", "")) if p.get("ref") else ""
        alt = _esc(p.get("alt", ""))
        if not src:
            return (f'<figure class="{cls} fg-block-missing">'
                    f"[image: no reference set]</figure>")
        return f'<img class="{cls}" src="{src}" alt="{alt}">'
    if t == "icon":
        size = _esc(p.get("size", 32))
        src = _ref(con, p.get("ref", "")) if p.get("ref") else ""
        if not src:
            return (f'<span class="fg-block-missing">[icon]</span>')
        return (f'<img class="{cls}" src="{src}" width="{size}"'
                f' height="{size}" alt="{_esc(p.get("alt", "icon"))}">')
    if t == "button":
        return (f'<a class="fg-button {cls}" href="{_esc(p.get("href", "#"))}">'
                f"{_esc(p.get('text', 'Button'))}</a>")
    if t == "palette":
        # swatch strip from a linked palette: [[ slug ]] or palette id
        ref = p.get("ref", "")
        hexes = _palette_hexes(con, ref)
        if not hexes:
            return (f'<div class="fg-block-missing">[palette {ref}]</div>')
        cells = "".join(
            f'<span style="display:inline-block;width:40px;height:40px;'
            f'border-radius:8px;background:{_esc(h)}"'
            f' title="{_esc(h)}"></span>' for h in hexes)
        return f'<div class="fg-palette {cls}">{cells}</div>'
    if t == "font":
        # font specimen: family name + pangram at several sizes
        fam = _esc(p.get("family", ""))
        if not fam:
            return '<div class="fg-block-missing">[font]</div>'
        return (f'<div class="fg-fontspec {cls}" style="font-family:'
                f"'{fam}'\">"
                f'<div style="font-size:28px">Sphinx of black quartz</div>'
                f'<div style="font-size:18px">judge my vow — {fam}</div>'
                f"</div>")
    if t == "snippet":
        ref = p.get("ref", "")
        body = _snippet_body(con, ref)
        if body is None:
            return (f'<div class="fg-block-missing">[snippet {ref}]</div>')
        return body
    if t == "html":
        # raw embed is intentional power-user markup; it flows through
        # the SAME sandboxed preview as everything else
        return str(p.get("html", ""))
    return f"<!-- unknown block {t} -->"


def _palette_hexes(con, ref: str) -> list[str]:
    try:
        if ref.isdigit():
            rows = con.execute(
                "SELECT hex FROM palette_color WHERE palette_id = ?"
                " ORDER BY position", (int(ref),)).fetchall()
            return [r[0] for r in rows]
        hit = assetrefs.resolve(con, ref)
        if hit and hit.get("kind") == "palette":
            rows = con.execute(
                "SELECT hex FROM palette_color WHERE palette_id = ?"
                " ORDER BY position", (int(hit["id"]),)).fetchall()
            return [r[0] for r in rows]
    except Exception:
        pass
    return []


def _snippet_body(con, ref: str):
    try:
        if ref.isdigit():
            row = con.execute("SELECT body FROM snippet WHERE id = ?",
                              (int(ref),)).fetchone()
            return row[0] if row else None
        hit = assetrefs.resolve(con, ref)
        if hit and hit.get("kind") == "snippet":
            row = con.execute("SELECT body FROM snippet WHERE id = ?",
                              (int(hit["id"]),)).fetchone()
            return row[0] if row else None
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────── templates
def template_vars(settings: dict) -> dict:
    return dict((settings or {}).get("template_vars") or {})


def set_template_var(settings: dict, name: str, value: str) -> dict:
    if not _VAR_RE.match("{{ %s }}" % (name or "")):
        raise StudioError("variable names are [A-Za-z_] + word chars")
    s = dict(settings or {})
    s.setdefault("template_vars", {})[name] = str(value)
    return s


def apply_vars(obj: Any, variables: dict) -> Any:
    """Recursively substitute {{name}} in every string of a JSON-ish
    structure. Unknown variables stay literal (visible while authoring)."""
    if isinstance(obj, str):
        return _VAR_RE.sub(
            lambda m: str(variables.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, list):
        return [apply_vars(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: apply_vars(v, variables) for k, v in obj.items()}
    return obj


def instantiate_template(con, template_id: int, name: str,
                         overrides: dict | None = None) -> int:
    """Create a tenant/implementation instance of a template project:
    copies pages + settings, records template_of, applies var overrides."""
    row = con.execute(
        "SELECT name, settings FROM projects WHERE id = ?",
        (int(template_id),)).fetchone()
    if row is None:
        raise StudioError(f"no project #{template_id}")
    s = json.loads(row["settings"] or "{}")
    s["template_vars"] = dict((s.get("template_vars") or {}))
    s.setdefault("template_vars", {}).update(overrides or {})
    s["template_of"] = int(template_id)
    cur = con.execute(
        "INSERT INTO projects(name, description, tags, settings)"
        " VALUES (?, ?, ?, ?)",
        ((name or row["name"]).strip(), "Instance of project #%s"
         % template_id, "", json.dumps(s)))
    new_id = cur.lastrowid
    # copy the pages, with vars applied at copy time so the instance is
    # independently editable afterwards
    for pg in list_pages(con, template_id):
        full = get_page(con, pg["id"])
        payload = apply_vars(full["payload"],
                             dict(s["template_vars"]))
        con.execute(
            "INSERT INTO studio_page(project_id, name, kind, sort,"
            " payload, guid) VALUES (?,?,?,?,?,?)",
            (new_id, pg["name"], pg["kind"], pg["sort"],
             json.dumps(payload), core_db.new_guid()))
    con.commit()
    return new_id


def instances_of(con, template_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT id, name, updated FROM projects"
        " WHERE json_extract(settings, '$.template_of') = ?"
        " ORDER BY name", (int(template_id),)).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────── characterization
def describe_usage(con, project_id: int) -> dict:
    """Asset-usage + link stats for the Docs/analyze screen."""
    pages = list_pages(con, project_id)
    refs: dict[str, int] = {}
    types: dict[str, int] = {}

    def count(tree: list) -> None:
        for b in tree:
            types[b.get("type", "?")] = types.get(b.get("type", "?"), 0) + 1
            ref = (b.get("props") or {}).get("ref")
            if ref:
                refs[ref] = refs.get(ref, 0) + 1
            count(b.get("children", []))

    for pg in pages:
        full = get_page(con, pg["id"])
        count(full["payload"])
    assets = con.execute(
        "SELECT asset_kind, COUNT(*) AS n FROM project_asset"
        " WHERE project_id = ? GROUP BY asset_kind",
        (int(project_id),)).fetchall()
    attached = {r["asset_kind"]: r["n"] for r in assets}
    unresolved = [r for r in refs
                  if assetrefs.resolve(con, r) is None]
    return {
        "pages": len(pages),
        "blocks": sum(types.values()),
        "block_types": types,
        "refs": refs,
        "unresolved_refs": unresolved,
        "attached_assets": attached,
    }
