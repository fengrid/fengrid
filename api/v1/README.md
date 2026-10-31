# Fengrid REST API — v1

A lightweight, stdlib-only HTTP API over the same core modules the
desktop app uses. No new dependencies, no Qt required — it runs headless
on any machine with the repo (or the installed `fengrid` package).

## Quick start

```bash
# from the repo root
python -m api.v1 --db ~/.local/share/fengrid/library.db --port 8642
# → prints "token: <generated>" on startup
```

Options: `--host`, `--port`, `--data-dir` (defaults to the db's parent),
`--token <tok>` or `FENGRID_API_TOKEN`, `--insecure` (localhost only),
`--workers N` (job threads, default 3), `--verbose`.

Every request needs `Authorization: Bearer <token>` (also `OPTIONS`
preflight is open). Long operations (ingest, export, backup, restore,
DB admin) return **202** with `{"id", "state", "kind"}` — poll
`GET /jobs/{id}` until `state` is `done`/`failed`; the `result` field
carries the operation's report.

## Surface

| Area      | Endpoints |
|-----------|-----------|
| System    | `GET /health`, `GET /inventory` |
| Assets    | `GET /assets?kind=&q=&collection=&starred=`, `GET/PATCH /assets/{kind}/{id}` (describe / rename+tags+fields), `POST .../star`, `POST .../tags`, `POST .../collect`, `DELETE .../collect/{ref}`, `POST .../copy` |
| Ingest    | `POST /assets/ingest` — files, zip, or folder; `mode: copy|link` |
| Export    | `POST /assets/export` — scopes `icons` (formats/size/tint/script), `fonts` (webfonts/weights), `palettes` (css/json/txt/csv/md code lists), `snippets`, `bundle` |
| Collections | `GET/POST /collections`, `GET/DELETE /collections/{id}`, `GET/POST /collections/{id}/refs` |
| Libraries | `GET/POST /libraries` (saved tag-driven views) |
| Tags      | `GET /tags`, `PATCH/DELETE /tags/{name}` |
| Fields    | `GET/POST /fields`, `DELETE /fields/{id}` (custom field defs) |
| Projects  | `GET /projects`, `GET /projects/{id}` |
| Backup    | `GET/POST /backups`, `POST /backup/restore` |
| DB admin  | `POST /db/{check,vacuum,checkpoint,optimize,rebuild_fts,sweep}` |
| Watch     | `GET/POST /watch`, `DELETE /watch/{id}`, `POST /watch/{id}/run` (501 headless) |
| Jobs      | `GET /jobs`, `GET/DELETE /jobs/{id}` |

Full request/response shapes: [`openapi.yaml`](openapi.yaml) (import it
into Swagger UI/Insomnia) and
[`postman_collection.json`](postman_collection.json) (set the `base` and
`token` collection variables).

## Example

```bash
TOKEN=...
curl -s -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"scope":"icons","dest":"/tmp/out","paths":["/tmp/a.svg"],
          "opts":{"formats":["png","webp"],"size":256,"tint":"#ff5500"}}' \
     http://127.0.0.1:8642/api/v1/assets/export
# → {"ok":true,"data":{"id":"ab12cd34","state":"queued","kind":"export"}}
curl -s -H "Authorization: Bearer $TOKEN" \
     http://127.0.0.1:8642/api/v1/jobs/ab12cd34
```

## Design notes

- **Middleware** (`middleware.py`): bearer auth (constant-time compare),
  request log line, 10 MB body cap, uniform `{ok, data}` / `{ok:false,
  error:{code,message,status}}` envelope, permissive CORS for local tooling.
- **Scheduler** (`scheduler.py`): FIFO queue + worker threads; jobs are
  transient (in-memory registry, newest 100 finished kept); cooperative
  cancel via `DELETE /jobs/{id}`.
- **Handlers** (`resources.py`): thin bindings over `fengrid.core.*` —
  the same functions the desktop app's DataIO bridge calls, so API and
  app behaviour stay identical.
- The API opens its **own** sqlite connections per request/job (sqlite is
  thread-affine); it never shares the desktop app's live connection.
  Run the API against a database the app is *not* writing to, or accept
  WAL-mode concurrent access.
