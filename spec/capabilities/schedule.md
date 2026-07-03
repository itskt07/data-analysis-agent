# Capability: Schedule EDA Runs & Delivery

> **Phase 3 — ACTIVE.** Wires the previously-stubbed "Schedule runs" tile into real functionality. Reuses the Phase-1 EDA pipeline; adds no new agent graph (see [../agent.md](../agent.md)).

## What It Does
Lets a user save a CSV + cadence as a schedule that re-runs the EDA analysis on a recurring interval (and on demand via "Run now"), records each execution as a normal EDA run, and optionally delivers a JSON payload to a webhook after each run.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | CSV (multipart) | `POST /schedules` upload | yes |
| interval_minutes | integer (≥ 1) | request form field | yes |
| webhook_url | string (URL) | request form field | no |
| name | string | request form field | no (defaults to filename) |
| schedule_id | string (UUID) | path param (`/run`, `GET`, `DELETE`) | for those routes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| schedule | JSON summary (`schedule_id`, cadence, `active`, `last_run_at`) | `POST /schedules`, `GET /schedules[/{id}]` response |
| run history | array of run link objects | `GET /schedules/{id}` → `runs[]` |
| EDA run | `Run` row + self-contained HTML report | `runs` table + `GET /runs/{run_id}/report` |
| webhook payload | JSON `{schedule_id, run_id, status, report_url}` | the configured `webhook_url` (POST) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| APScheduler `BackgroundScheduler` (in-process) | Fire `execute_schedule` on the interval | Job errors are logged; schedule stays registered |
| EDA pipeline (`run_agent`, reuses Gemini narrate) | Produce the EDA run + report | Fatal to that run only (recorded as `failed`); does not stop the schedule |
| Webhook endpoint (`webhook_url`) | POST the JSON payload after each run | **Non-fatal** — logged and skipped; the run is still recorded |
| SQLite | Persist schedule (incl. `csv_bytes` BLOB) + link runs | Write failure surfaces as an API error |

## Business Rules
- **In-process only** — APScheduler `BackgroundScheduler` started in the FastAPI lifespan; no Celery/Redis/RQ. Jobs run in the same process, synchronously reusing the EDA pipeline.
- **Opt-in raw-row persistence** — the schedule stores the uploaded CSV bytes inline (`schedules.csv_bytes`) so it can re-run without re-upload; this is the only place raw rows persist. The PII-to-LLM rule is unchanged (only aggregated stats reach Gemini).
- **Startup re-registration** — on server start, every `active` schedule is re-registered from the DB; missed fires while the process was down are not back-filled.
- **Run now** (`POST /schedules/{id}/run`) executes the identical logic synchronously and returns the created run, so it is testable without waiting for the interval.
- **Delete** removes the schedule and unregisters its job; runs it already produced are retained (their `schedule_id` is nulled).
- Cadence is `interval_minutes` only; cron cadence, auth, and email/Slack delivery are deferred to Phase 4.

## Success Criteria
- [ ] `POST /schedules` with a fixture CSV + `interval_minutes` returns a `schedule_id` with `active=true` and empty run history; `GET /schedules` lists it.
- [ ] `POST /schedules/{id}/run` (Run now) creates a `completed` `runs` row and returns it; `GET /schedules/{id}` then shows that run in `runs[]` with a `report_url`, and `GET /runs/{run_id}/report` returns the HTML report.
- [ ] A schedule with a `webhook_url` pointing at a real local HTTP listener delivers a payload containing `schedule_id`, `run_id`, `status`, `report_url` after Run now; an unreachable `webhook_url` still records the run as `completed` (non-fatal).
- [ ] `DELETE /schedules/{id}` removes the schedule (subsequent `GET` → 404) and unregisters its job.
- [ ] Error cases return the right status: no file / non-CSV / empty CSV / missing-or-invalid `interval_minutes` → 400; unknown `schedule_id` on `GET`/`run`/`DELETE` → 404.
- [ ] `uv run pytest tests/integration/test_scheduling.py -v` passes against the real Gemini key, and the full suite (`uv run pytest -v`) stays green.
