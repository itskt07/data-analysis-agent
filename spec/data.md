# Data Model

## Storage Technology

**SQLite** (via SQLAlchemy 2.0) is the only store in Phase 1. It holds run metadata **and the rendered report HTML** (stored inline in a `report_html` TEXT column — chosen over a separate artifact store so the report is fully self-contained and there is no filesystem/object-store dependency). Tables are created at startup by `init_db()` → `Base.metadata.create_all`; no Alembic migration step. Default URL: `sqlite:///./data/agent.db` (`AGENT_DATABASE_URL`).

The uploaded CSV is written to a temporary local path only for the duration of the synchronous run; raw rows are never persisted in the DB and never sent to the LLM.

> **Assumed:** the report HTML is stored inline in a `report_html` TEXT column (self-contained, base64-embedded charts) rather than on a filesystem/object store — this keeps Phase 1 free of any artifact-store dependency.

## Entities

### Entity: Run

Represents a single user-initiated EDA run. (Extends the skeleton's `RunRow`.)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key (`run_id`) |
| status | text (enum) | yes | `pending`, `completed`, `failed` |
| filename | text | no | Original uploaded CSV filename |
| narrative | text | no | Gemini narrative, or the templated fallback |
| report_html | text | no | The full self-contained HTML report (null on failure) |
| error_message | text | no | Set when `status = failed` |
| schedule_id | text (UUID) | no | **Phase 3** — set when this run was produced by a schedule (nullable FK → `schedules.id`); null for ad-hoc `POST /runs` |
| created_at | timestamp | yes | Creation time |
| updated_at | timestamp | yes | Last update time |

> The skeleton's existing `input_text` / `output_text` columns are repurposed/replaced by `filename`, `narrative`, and `report_html` for the EDA capability.
> **Phase 3:** the nullable `schedule_id` column links a run back to the schedule that produced it (used by `GET /schedules/{id}` to build run history). Ad-hoc EDA runs leave it null. Deleting a schedule nulls this column on its runs (the runs are retained) — see below.

### Entity: TrainingRun (Phase 2)

Represents a single user-initiated model-training run. Stored in its own table `training_runs`, **separate from `runs`** (the training flow has a dedicated graph mirroring the EDA flow). The trained model artifact (a joblib-serialized scikit-learn `Pipeline`) is stored **inline in the DB as a BLOB** — consistent with the Phase-1 inline-report decision (no filesystem/object store).

Table `training_runs`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key (`train_id`) |
| status | text (enum) | yes | `pending`, `completed`, `failed` |
| filename | text | no | Original uploaded CSV filename |
| target_column | text | yes | The label column selected by the user |
| algorithm | text | yes | Requested algorithm: `auto`, `logistic_regression`, `random_forest` |
| task_type | text (enum) | no | Detected task: `classification` or `regression` (null on early failure) |
| metrics | text (JSON) | no | Evaluation metrics, serialized as a JSON string |
| feature_columns | text (JSON) | no | Feature column names used, serialized as a JSON string |
| artifact | blob (LargeBinary) | no | joblib-serialized fitted `Pipeline` bytes (null on failure) |
| n_rows | integer | no | Number of rows used after dropping missing-target rows |
| n_features | integer | no | Number of feature columns |
| insight | text | no | Gemini metrics summary, or the templated fallback |
| error_message | text | no | Set when `status = failed` |
| created_at | timestamp | yes | Creation time |
| updated_at | timestamp | yes | Last update time |

Tables are still auto-created at startup via `Base.metadata.create_all` (`init_db()`); no Alembic migration step.

> **Assumed:** the joblib model artifact is stored inline in the `artifact` LargeBinary/BLOB column (never on a filesystem/object store) — consistent with the Phase-1 inline-report decision, keeping the project free of any artifact-store dependency.

### Entity: Schedule (Phase 3)

Represents a saved, recurring EDA analysis over a stored dataset. Stored in its own table `schedules`. To re-run without re-upload, the schedule stores the uploaded CSV bytes inline as a BLOB — the **one deliberate, opt-in exception** to the "raw rows are never persisted" rule (it applies only to datasets a user explicitly attaches to a schedule; see [roadmap.md](roadmap.md) Key Constraints). The PII-to-LLM rule is unchanged: scheduled runs still send only aggregated stats to Gemini.

Table `schedules`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key (`schedule_id`) |
| name | text | no | Human label (defaults to the filename) |
| filename | text | no | Original uploaded CSV filename |
| csv_bytes | blob (LargeBinary) | yes | The stored uploaded CSV bytes, re-fed to the EDA pipeline each execution (opt-in raw-row persistence) |
| interval_minutes | integer | yes | Cadence in minutes (≥ 1) — the interval trigger for the scheduler |
| webhook_url | text | no | If set, a JSON payload is POSTed after each execution (non-fatal on failure) |
| active | boolean | yes | Whether the scheduler fires this schedule; only `active` schedules are re-registered on startup. Default `true` |
| last_run_at | timestamp | no | When the schedule last executed (null until first run) |
| created_at | timestamp | yes | Creation time |
| updated_at | timestamp | yes | Last update time |

Tables are still auto-created at startup via `Base.metadata.create_all` (`init_db()`); no Alembic migration step.

> **Assumed:** the schedule's CSV bytes are stored inline in a `csv_bytes` LargeBinary/BLOB column (never on a filesystem/object store) — consistent with the Phase-1 inline-report and Phase-2 inline-artifact decisions, keeping the project free of any object-store dependency for datasets ≤ 50 MB.

## Relationships

- `Run` (EDA) and `TrainingRun` (training) are **independent** — training is a separate flow with its own table and graph. There is no foreign-key link (a training run is initiated by its own CSV upload, not derived from an EDA run).
- **Phase 3:** `Schedule` **1 — N** `Run`. Each scheduled/Run-now execution creates a normal `Run` with `runs.schedule_id = schedules.id`. `GET /schedules/{id}` reads its run history via this link. Deleting a schedule removes the `schedules` row and **nulls `schedule_id`** on its runs (the produced runs and their reports are retained). `Schedule` has no link to `TrainingRun` (Phase 3 schedules re-run EDA only, not training).

## Data Lifecycle

- For ad-hoc EDA (`POST /runs`) and training (`POST /train`), the uploaded CSV lives in memory only during the synchronous run, then is discarded.
- The `Run` row (including `report_html`) and the `TrainingRun` row (including the joblib `artifact` BLOB) persist in SQLite until deleted. No automatic retention policy.
- **Phase 3 exception:** a `Schedule`'s `csv_bytes` persist inline for the life of the schedule (so it can re-run on its cadence) and are deleted when the schedule is deleted. This is the only place raw rows are stored, and only for datasets the user explicitly attached to a schedule.

## Sensitive Data

- CSVs may contain PII. The system:
  - Never sends raw rows to the LLM — only derived, aggregated statistics (EDA) or aggregated metrics + column/feature names (training). **Unchanged in Phase 3** — scheduled runs send only aggregated stats to Gemini.
  - Never persists raw rows in the database, **with one opt-in exception**: a `Schedule`'s `csv_bytes` (Phase 3), stored only for user-created schedules so they can re-run. The training `artifact` BLOB is a serialized model `Pipeline` (learned parameters), not raw rows.
  - Logs no raw cell values (only aggregate counts/metadata/metrics, plus schedule/run ids and webhook outcomes).
