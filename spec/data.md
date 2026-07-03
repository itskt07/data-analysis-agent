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

### Entity: ModelArtifact (Phase 2 — deferred)

Metadata about trained models. Not created in Phase 1.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Artifact id |
| run_id | text (UUID) | yes | Linking run |
| path | text | yes | Artifact path/location |
| metrics | json | no | Evaluation metrics |
| created_at | timestamp | yes | When produced |

## Relationships

- `Run` 1:N `ModelArtifact` — deferred to Phase 2 (a Phase-2 run may produce a model artifact).

## Data Lifecycle

- The uploaded CSV lives on a temporary local path only during the synchronous run, then is discarded.
- The `Run` row (including `report_html`) persists in SQLite until deleted. No automatic retention policy in Phase 1.

## Sensitive Data

- CSVs may contain PII. The system:
  - Never sends raw rows to the LLM — only derived, aggregated statistics.
  - Never persists raw rows in the database.
  - Logs no raw cell values (only aggregate counts/metadata).
