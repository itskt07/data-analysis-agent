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

Real panels (built in later phases, no stubs remain):
- **Train a model (Phase 2)** — the real Train panel (upload + target column + algorithm → metrics + Download model).
- **Schedule runs (Phase 3)** — the real Schedule panel (below).

### Screen: Schedule panel (Phase 3 — part of `frontend/src/app/page.tsx`)

Purpose: create recurring EDA schedules over a stored CSV, view run history, trigger Run now, and delete. Replaces the former "Schedule runs — Coming soon" stub.

Key elements (all real, on the tested path):
- **Create-schedule form** — a CSV file input + an `interval_minutes` number input (≥ 1) + an optional `webhook_url` text input + an optional `name` text input + a Create button → `POST /schedules` (multipart). Inline validation for missing file / non-CSV / invalid interval.
- **Schedules list** — each schedule shows its `name`, `filename`, `interval_minutes`, `webhook_url` (if any), `active`, and `last_run_at`, sourced from `GET /schedules`.
- **Run history (per schedule)** — expanding a schedule calls `GET /schedules/{id}` and lists its runs (most-recent first) with status and a link that opens the run's report (`GET /runs/{run_id}/report`), same as the Phase 1 report viewer.
- **Run now button** — `POST /schedules/{id}/run`; on completion the new run appears at the top of that schedule's run history within seconds (no waiting for the interval).
- **Delete button** — `DELETE /schedules/{id}`; removes the schedule from the list.

## Interaction Flow

1. User selects/drops a CSV → clicks Analyze.
2. Frontend `POST /runs` (multipart, field `file`) → shows progress.
3. On `status: "completed"`, embed the report from `report_url` and enable Download; show the narrative.
4. On `400/413` or `status: "failed"`, show the inline/box error.

## Error States

- Inline validation for upload problems (non-CSV, empty, too large).
- Run-level failure shows a clear error box including `run_id`.

## E2E Tests

A `frontend/tests/e2e/` Playwright suite covers the primary journey: load `/app/`, upload a fixture CSV, wait for the report to render, and assert the report iframe + download button appear. This suite is a Phase 1 deliverable and runs against the real running app. (The Phase-1 test asserted the Train/Schedule sections were "Coming soon"; those stubs were replaced by real panels in Phases 2 and 3, and the corresponding e2e assertions were updated with each phase.)

**Phase 3 e2e:** a Playwright test covers the schedule journey — create a schedule from a fixture CSV with an `interval_minutes`, click **Run now**, and assert a run appears in that schedule's run history with a viewable report link. Interval-based firing is not asserted (Run now is the deterministic path).
