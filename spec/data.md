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
| created_at | timestamp | yes | Creation time |
| updated_at | timestamp | yes | Last update time |

> The skeleton's existing `input_text` / `output_text` columns are repurposed/replaced by `filename`, `narrative`, and `report_html` for the EDA capability.

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

## Relationships

- `Run` (EDA) and `TrainingRun` (training) are **independent** — training is a separate flow with its own table and graph. There is no foreign-key link in Phase 2 (a training run is initiated by its own CSV upload, not derived from an EDA run).

## Data Lifecycle

- The uploaded CSV lives in memory only during the synchronous run, then is discarded (both EDA and training).
- The `Run` row (including `report_html`) and the `TrainingRun` row (including the joblib `artifact` BLOB) persist in SQLite until deleted. No automatic retention policy.

## Sensitive Data

- CSVs may contain PII. The system:
  - Never sends raw rows to the LLM — only derived, aggregated statistics (EDA) or aggregated metrics + column/feature names (training).
  - Never persists raw rows in the database. The training `artifact` BLOB is a serialized model `Pipeline` (learned parameters), not raw rows.
  - Logs no raw cell values (only aggregate counts/metadata/metrics).
