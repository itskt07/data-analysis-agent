# UI

## UI Type

Single-page Next.js static-export app, served **same-origin** by FastAPI at `/app/`. It calls the backend via relative paths (e.g. `/runs`) with **no `/api/v1` prefix**. The whole Phase 1 flow lives on one page.

## Views / Screens

### Screen: Upload + Report (single page — `frontend/src/app/page.tsx`)

Purpose: upload a CSV, run EDA, and view/download the resulting report.

Key elements (real, on the tested path):
- **CSV upload** — a dropzone / file input that accepts a single `.csv`.
- **Progress state** — a "Running analysis…" indicator while the synchronous `POST /runs` request is in flight.
- **Report viewer** — embeds the returned HTML report same-origin (via `iframe` `src=/runs/{run_id}/report` or `srcdoc`).
- **Download button** — downloads the self-contained HTML report.
- **Error states** — inline validation for bad uploads (non-CSV, empty, too large) and a clear error box (with `run_id`) if a run fails.

Labelled NON-FUNCTIONAL stubs (must visibly read "Coming soon" so they are never mistaken for bugs):
- **Train a model (Phase 2)** — disabled section marked "Coming soon".
- **Schedule runs (Phase 3)** — disabled section marked "Coming soon".

## Interaction Flow

1. User selects/drops a CSV → clicks Analyze.
2. Frontend `POST /runs` (multipart, field `file`) → shows progress.
3. On `status: "completed"`, embed the report from `report_url` and enable Download; show the narrative.
4. On `400/413` or `status: "failed"`, show the inline/box error.

## Error States

- Inline validation for upload problems (non-CSV, empty, too large).
- Run-level failure shows a clear error box including `run_id`.

## E2E Tests

A `frontend/tests/e2e/` Playwright suite covers the primary journey: load `/app/`, upload a fixture CSV, wait for the report to render, and assert the report iframe + download button appear and the Train/Schedule sections are labelled "Coming soon". This suite is a Phase 1 deliverable and runs against the real running app.
