# API

## API Style

RESTful endpoints served by FastAPI on port 8001, **same-origin** with the static frontend mounted at `/app/`. Routes are mounted at **root — no `/api/v1` prefix**. JSON responses use the skeleton's envelope `ok(data)` → `{ "data": ..., "error": null }`; the report endpoint returns a raw HTML document and the train-artifact endpoint returns raw joblib bytes (both not enveloped). **No authentication.**

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

### `POST /train` (Phase 2)

Train a scikit-learn model on a labeled CSV. Runs **synchronously** — the response returns after training + evaluation complete. Routes mounted at root, no auth. Handled by the dedicated training graph (see [agent.md](agent.md)).

Request: `multipart/form-data`
- **`file`** — the CSV file (required).
- **`target_column`** — the label column name (form field, required).
- **`algorithm`** — form field, optional; one of `auto` (default), `logistic_regression`, `random_forest`.

Response (`ok(...)`):
```json
{
  "data": {
    "train_id": "<uuid>",
    "status": "completed",
    "task_type": "classification | regression",
    "algorithm": "auto | logistic_regression | random_forest",
    "target_column": "<string>",
    "metrics": { "accuracy": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0, "n_classes": 0, "classes": [], "n_test": 0 },
    "feature_columns": ["<string>"],
    "artifact_url": "/train/<uuid>/artifact",
    "insight": "<string>",
    "error": null
  },
  "error": null
}
```
`status` is `"completed"` on success or `"failed"` on a pipeline error (with `error` set and `metrics`/`artifact_url` possibly null). `metrics` shape depends on `task_type`: classification → `accuracy, f1, precision, recall, n_classes, classes, n_test`; regression → `r2, mae, rmse, n_test`.

Error cases:

| Status | Condition |
|--------|-----------|
| 400 | Missing file, non-CSV file, empty CSV, missing `target_column`, `target_column` not a column in the CSV, or too few rows to train |
| 413 | File too large (limit: 50 MB) |

### `GET /train/{train_id}` (Phase 2)

Fetch a training run's status, metrics, and links.

Response (`ok(...)`): same summary object as `POST /train`.

| Status | Condition |
|--------|-----------|
| 404 | Unknown `train_id` |

### `GET /train/{train_id}/artifact` (Phase 2)

Return the raw joblib-serialized model artifact bytes as `application/octet-stream` (NOT enveloped) with `Content-Disposition: attachment; filename="model_<train_id>.joblib"`.

| Status | Condition |
|--------|-----------|
| 404 | Unknown `train_id`, or artifact missing (failed run) |

### `POST /schedules` (Phase 3)

Create a schedule that re-runs an EDA analysis on a stored CSV on a recurring cadence. The uploaded CSV bytes are stored inline on the schedule row (opt-in raw-row persistence — see [data.md](data.md)). Creating a schedule registers an interval job with the in-process scheduler ([agent.md](agent.md)). Routes mounted at root, no auth.

Request: `multipart/form-data`
- **`file`** — the CSV file (required).
- **`interval_minutes`** — integer ≥ 1, the cadence (form field, required).
- **`webhook_url`** — form field, optional; if set, a JSON payload is POSTed after each execution.
- **`name`** — form field, optional; a human label (defaults to the filename).

Response (`ok(...)`):
```json
{
  "data": {
    "schedule_id": "<uuid>",
    "name": "<string>",
    "filename": "<string>",
    "interval_minutes": 15,
    "webhook_url": "<string | null>",
    "active": true,
    "last_run_at": null,
    "created_at": "<iso-8601>",
    "runs": []
  },
  "error": null
}
```

Error cases:

| Status | Condition |
|--------|-----------|
| 400 | Missing file, non-CSV file, empty CSV, or missing / non-integer / `< 1` `interval_minutes` |
| 413 | File too large (limit: 50 MB) |

### `GET /schedules` (Phase 3)

List all schedules (summary — without `runs`).

Response (`ok(...)`): an array of schedule summary objects (the same fields as `POST /schedules` **excluding** `runs`).

### `GET /schedules/{schedule_id}` (Phase 3)

Fetch one schedule **including its run history**. `runs` is an array (most-recent first) of the EDA runs this schedule has produced, each a compact link object:

```json
{
  "data": {
    "schedule_id": "<uuid>",
    "name": "<string>",
    "filename": "<string>",
    "interval_minutes": 15,
    "webhook_url": "<string | null>",
    "active": true,
    "last_run_at": "<iso-8601 | null>",
    "created_at": "<iso-8601>",
    "runs": [
      { "run_id": "<uuid>", "status": "completed | failed", "report_url": "/runs/<uuid>/report", "created_at": "<iso-8601>" }
    ]
  },
  "error": null
}
```

| Status | Condition |
|--------|-----------|
| 404 | Unknown `schedule_id` |

### `POST /schedules/{schedule_id}/run` (Phase 3)

**Run now** — execute the schedule immediately, **synchronously** (does not wait for the interval). Reuses the EDA pipeline on the schedule's stored CSV, creates a normal `runs` row, updates `last_run_at`, and POSTs the webhook if configured (non-fatal). Returns the created run in the same shape as `POST /runs`.

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

The produced run is a normal `Run` — its report is served by the existing `GET /runs/{run_id}/report`.

| Status | Condition |
|--------|-----------|
| 404 | Unknown `schedule_id` |

### `DELETE /schedules/{schedule_id}` (Phase 3)

Delete a schedule and unregister its scheduler job. The `runs` it already produced are **retained** (their `schedule_id` is left dangling / nulled per [data.md](data.md)).

Response (`ok(...)`): `{ "data": { "schedule_id": "<uuid>", "deleted": true }, "error": null }`.

| Status | Condition |
|--------|-----------|
| 404 | Unknown `schedule_id` |

### `GET /health`

Liveness check (from the skeleton). Returns `ok(...)` with basic status.

## Deferred to future phases

- **Live now:** the run endpoints (Phase 1), the train endpoints `POST /train`, `GET /train/{id}`, `GET /train/{id}/artifact` (Phase 2), and the schedule endpoints `POST /schedules`, `GET /schedules`, `GET /schedules/{id}`, `POST /schedules/{id}/run`, `DELETE /schedules/{id}` (Phase 3). No auth in any phase yet.
- **Deferred to Phase 4:** auth (JWT / API key), `POST /runs/{run_id}/cancel`, URL-based ingest (`url` field), cron-string cadence for schedules (Phase 3 uses `interval_minutes` only), and email/Slack delivery (Phase 3 delivers via webhook only).
