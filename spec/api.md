# API

## API Style

RESTful endpoints served by FastAPI on port 8001, **same-origin** with the static frontend mounted at `/app/`. Routes are mounted at **root — no `/api/v1` prefix**. JSON responses use the skeleton's envelope `ok(data)` → `{ "data": ..., "error": null }`; the report endpoint returns a raw HTML document (not enveloped). **No authentication in Phase 1.**

## Endpoints

### `POST /runs`

Start a new EDA run. Runs **synchronously** — the response returns after the report is produced.

Request: `multipart/form-data`
- **`file`** — the CSV file (required).

Response (`ok(...)`):
```json
{
  "data": {
    "run_id": "<uuid>",
    "status": "completed",
    "report_url": "/runs/<uuid>/report",
    "narrative": "<string>",
    "error": null
  },
  "error": null
}
```
`status` is `"completed"` on success or `"failed"` on a pipeline error (with `error` set and `narrative`/`report_url` possibly null).

Error cases:

| Status | Condition |
|--------|-----------|
| 400 | Missing file, non-CSV file, or empty CSV |
| 413 | File too large (limit: 50 MB) |

### `GET /runs/{run_id}`

Fetch a run's status and links.

Response (`ok(...)`):
```json
{
  "data": {
    "run_id": "<uuid>",
    "status": "completed | failed",
    "report_url": "/runs/<uuid>/report",
    "narrative": "<string | null>",
    "error": "<string | null>"
  },
  "error": null
}
```

| Status | Condition |
|--------|-----------|
| 404 | Unknown `run_id` |

### `GET /runs/{run_id}/report`

Return the raw self-contained **HTML report** as an `HTMLResponse` (NOT enveloped — it is a document the UI embeds via iframe/srcdoc and offers for download).

| Status | Condition |
|--------|-----------|
| 404 | Unknown `run_id`, or report not yet produced (failed run) |

### `GET /health`

Liveness check (from the skeleton). Returns `ok(...)` with basic status.

## Deferred to future phases

- Auth (JWT / API key), `POST /runs/{run_id}/cancel`, URL-based ingest (`url` field), and the `action` / `label_column` train parameters are **out of Phase 1** — added when Phase 2/3 is scoped. Local Phase 1 has no auth.
