"""Import engine: bring icon sets into icons/<theme>/ for fengrid.

Used by serve.py's /import endpoint. Four kinds of source:

  folder    an existing local directory (copied)
  archive   a .zip / .tar.gz / .tgz / .tar.bz2 / .tar.xz / .7z file or URL
  git       a git repository URL (shallow-cloned)
  iconify   a set from the fengrid/icon-sets catalog (Iconify JSON), rendered
            to one .svg file per icon

Every import places files under icons/<theme>/ and returns a summary dict;
the endpoint then runs the refresh + metadata pipeline so the new set is
listed and scanned. Only http(s) URLs are fetched; archives are unpacked
with Python's data filters (zip/tar slip protection) or the `7z` binary.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

MAX_DOWNLOAD = 512 * 1024 * 1024  # 512 MB cap for fetched archives
RAW_BASE = "https://raw.githubusercontent.com/fengrid/icon-sets/master/"
CATALOG_URL = RAW_BASE + "collections.json"
JSON_URL = RAW_BASE + "json/%s.json"
UA = "fengrid-import/1.0"

PREVIEW = {".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
CONVERTIBLE = {".xpm", ".icns"}  # converted to .png when a converter exists

ARCHIVE_EXTS = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz",
                ".txz", ".tar", ".7z")
GIT_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "git.sr.ht",
             "codeberg.org", "sourceforge.net")


def _http_get(url, timeout=60, max_bytes=MAX_DOWNLOAD):
    """Fetch up to max_bytes of a http(s) URL. Returns bytes."""
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("only http(s) URLs are supported")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("download exceeds the %d MB limit" % (max_bytes >> 20))
    return data


def _convert_to_png(src, dest):
    """Convert .xpm/.icns to .png via ImageMagick; returns True on success."""
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return False
    try:
        subprocess.run([magick, src, dest], capture_output=True, timeout=60,
                       check=True)
        return True
    except Exception:
        return False


def sanitize_name(raw):
    """Turn a user/source label into a safe single-path theme name."""
    name = re.sub(r"[^A-Za-z0-9._\-]+", "-", (raw or "").strip()).strip("-.")
    name = name[:40].strip("-.")
    return name or "imported-set"


def unique_theme(app_dir, name):
    """Return <name>, <name>-2, ... that does not collide in icons/."""
    icons_dir = os.path.join(app_dir, "icons")
    existing = {e.lower() for e in os.listdir(icons_dir)} if os.path.isdir(icons_dir) else set()
    name = sanitize_name(name)
    candidate, i = name, 1
    while candidate.lower() in existing:
        i += 1
        candidate = "%s-%d" % (name, i)
    return candidate


def _ensure_svg_xmlns(dest):
    """An <img>-loaded SVG must declare the SVG namespace; some sets omit it.

    Without xmlns the browser rejects the file as an image (the root element
    is not in the SVG namespace) and the card renders as MISSING. Rewrites
    the root <svg> tag in place when the attribute is missing.
    """
    try:
        with open(dest, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
        if "xmlns" in head.split(">", 1)[0]:
            return
        fixed = head.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        with open(dest, "r+b") as f:  # rewrite in place, preserving the tail
            rest = f.read()
            f.seek(0)
            f.write(fixed.encode("utf-8") + rest[len(head.encode("utf-8")):])
            f.truncate()
    except OSError:
        pass


def import_folder(src_dir, app_dir, name):
    """Copy the previewable files of a local directory into icons/<name>/."""
    src_dir = os.path.abspath(os.path.expanduser(src_dir))
    if not os.path.isdir(src_dir):
        raise ValueError("not a directory: " + src_dir)
    theme = unique_theme(app_dir, name or os.path.basename(src_dir))
    dest_root = os.path.join(app_dir, "icons", theme)
    os.makedirs(dest_root, exist_ok=True)

    copied = converted = skipped = 0
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            base, ext = os.path.splitext(fn)
            ext = ext.lower()
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, src_dir)
            dest = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if ext in PREVIEW:
                try:
                    shutil.copyfile(src, dest)
                    copied += 1
                    if ext == ".svg":
                        _ensure_svg_xmlns(dest)
                except OSError:
                    skipped += 1
            elif ext in CONVERTIBLE and _convert_to_png(src, dest[:-len(ext)] + ".png"):
                converted += 1
            else:
                skipped += 1
    return {"theme": theme, "imported": copied, "converted": converted,
            "skipped": skipped}


def _unpack(data, filename, dest):
    """Unpack an archive into dest with path-traversal protection."""
    filename = (filename or "").lower()
    if filename.endswith(".zip"):
        import zipfile
        import io
        # zipfile has no extraction filter (PEP 706 is tarfile-only), so vet
        # every member: reject absolute paths, drive letters, and traversal
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if (name.startswith("/") or ":" in name.split("/")[0]
                        or ".." in name.split("/")):
                    raise ValueError("unsafe archive entry: " + info.filename)
            z.extractall(dest)
        return
    if any(filename.endswith(e) for e in (".tar.gz", ".tgz", ".tar.bz2",
                                          ".tbz2", ".tar.xz", ".txz", ".tar")):
        import tarfile
        import io
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            try:
                t.extractall(dest, filter="data")
            except TypeError:  # Python < 3.12: no filter kwarg — reject unsafe members
                for m in t.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/"):
                        continue
                    t.extract(m, dest)
        return
    if filename.endswith(".7z"):
        exe = shutil.which("7z") or shutil.which("7za")
        if not exe:
            raise ValueError("no 7z binary installed (p7zip) — cannot unpack .7z")
        tmp = dest + ".7z"
        with open(tmp, "wb") as f:
            f.write(data)
        p = subprocess.run([exe, "x", "-y", "-o" + dest, tmp],
                           capture_output=True, timeout=600)
        os.unlink(tmp)
        if p.returncode != 0:
            raise ValueError("7z failed: " + p.stderr.decode("utf-8", "replace")[:200])
        return
    raise ValueError("unsupported archive type: " + (filename or "unknown"))


def _prune_single_root(dest):
    """If the tree has exactly one top-level dir, use its contents instead."""
    entries = os.listdir(dest)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0])
    return dest


def import_archive(data, filename, app_dir, name):
    """Unpack an archive (bytes + filename) and import its previewable files."""
    with tempfile.TemporaryDirectory(prefix="fengrid-import-") as tmp:
        unpack_dir = os.path.join(tmp, "x")
        os.makedirs(unpack_dir)
        _unpack(data, filename, unpack_dir)
        return import_folder(_prune_single_root(unpack_dir), app_dir, name)


def import_url(url, app_dir, name=None):
    """Import from a git repository URL or an archive URL / local path."""
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        raise ValueError("no URL given")
    # local path (file on the server's machine)?
    local = os.path.expanduser(url)
    if os.path.isdir(local):
        return import_folder(local, app_dir, name)
    if os.path.isfile(local):
        with open(local, "rb") as f:
            return import_archive(f.read(), local, app_dir, name or
                                  os.path.splitext(os.path.basename(local))[0])
    host = re.match(r"^https?://([^/]+)/", url, re.I)
    host = host.group(1).lower() if host else ""
    # archives first: explicit extensions, or code-hosting archive endpoints
    # (codeload.github.com/.../zip/refs/heads/master ends in a branch name)
    if (url.lower().endswith(ARCHIVE_EXTS) or "/zip/" in url or "/tarball/" in url
            or "/archive/" in url or "codeload." in host):
        data = _http_get(url)
        fname = os.path.basename(url.split("?")[0])
        if not fname.lower().endswith(ARCHIVE_EXTS):
            fname += ".zip"
        return import_archive(data, fname, app_dir, name)
    # git repositories: explicit .git or a known code host
    if url.endswith(".git") or any(host == h or host.endswith("." + h) for h in GIT_HOSTS):
        # git repository: shallow clone into a temp dir, then import
        if not shutil.which("git"):
            raise ValueError("git is not installed — clone manually and import the folder")
        with tempfile.TemporaryDirectory(prefix="fengrid-git-") as tmp:
            dest = os.path.join(tmp, "repo")
            p = subprocess.run(["git", "clone", "--depth", "1",
                                "--single-branch", url, dest],
                               capture_output=True, timeout=600)
            if p.returncode != 0:
                raise ValueError("git clone failed: " +
                                 p.stderr.decode("utf-8", "replace")[:200])
            return import_folder(_prune_single_root(dest), app_dir, name)
    # unknown shape: try it as an archive anyway, let the type fail loudly
    data = _http_get(url)
    return import_archive(data, os.path.basename(url.split("?")[0]), app_dir, name)


def import_iconify(set_prefix, app_dir, name=None):
    """Render a fengrid/icon-sets catalog set into one .svg per icon.

    The catalog stores Iconify JSON: icons are path bodies with optional
    per-icon or per-set dimensions, plus aliases pointing at parent icons.
    """
    data = json.loads(_http_get(JSON_URL % set_prefix, timeout=120).decode("utf-8"))
    default_w = data.get("width") or data.get("height") or 16
    default_h = data.get("height") or data.get("width") or 16
    icons = data.get("icons", {})
    aliases = data.get("aliases", {})
    theme = unique_theme(app_dir, name or set_prefix)
    dest_root = os.path.join(app_dir, "icons", theme)
    os.makedirs(dest_root, exist_ok=True)

    def box(entry, set_w, set_h):
        w = entry.get("width") or set_w
        h = entry.get("height") or set_h
        return w, h

    written = 0
    seen = set()

    def write_icon(icon_name, entry):
        nonlocal written
        body = entry.get("body")
        if not body:
            return
        w, h = box(entry, default_w, default_h)
        fname = re.sub(r"[^A-Za-z0-9._\-]", "_", icon_name)[:80] + ".svg"
        if fname in seen:  # two names sanitize to the same file
            return
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" '
               'width="%s" height="%s">%s</svg>' % (w, h, w, h, body))
        with open(os.path.join(dest_root, fname), "w", encoding="utf-8") as f:
            f.write(svg)
        seen.add(fname)
        written += 1

    for icon_name, entry in icons.items():
        if isinstance(entry, dict) and entry.get("body"):
            write_icon(icon_name, entry)
    for alias_name, entry in aliases.items():
        parent = icons.get(entry.get("parent")) if isinstance(entry, dict) else None
        if not parent:
            continue
        merged = dict(parent)
        for k in ("width", "height"):
            if entry.get(k):
                merged[k] = entry[k]
        write_icon(alias_name, merged)

    info = data.get("info", {})
    return {"theme": theme, "imported": written,
            "set": info.get("name", set_prefix),
            "license": (info.get("license") or {}).get("title", "unknown")}


def catalog():
    """The fengrid/icon-sets catalog (collections.json), hidden sets removed."""
    data = json.loads(_http_get(CATALOG_URL, timeout=120).decode("utf-8"))
    out = []
    for prefix, info in data.items():
        if info.get("hidden"):
            continue
        out.append({
            "prefix": prefix,
            "name": info.get("name", prefix),
            "total": info.get("total", 0),
            "category": info.get("category", ""),
            "license": (info.get("license") or {}).get("title", "unknown"),
            "licenseUrl": (info.get("license") or {}).get("url", ""),
            "author": (info.get("author") or {}).get("name", ""),
        })
    out.sort(key=lambda s: s["name"].lower())
    return out


if __name__ == "__main__":
    # manual use:  python3 import_engine.py <kind> <source> [app_dir] [name]
    kind, source = sys.argv[1], sys.argv[2]
    app = sys.argv[3] if len(sys.argv) > 3 else os.getcwd()
    name = sys.argv[4] if len(sys.argv) > 4 else None
    if kind == "folder":
        print(json.dumps(import_folder(source, app, name)))
    elif kind == "url":
        print(json.dumps(import_url(source, app, name)))
    elif kind == "iconify":
        print(json.dumps(import_iconify(source, app, name)))
    elif kind == "catalog":
        print(json.dumps(catalog()[:5]))
    else:
        raise SystemExit("kinds: folder | url | iconify | catalog")
