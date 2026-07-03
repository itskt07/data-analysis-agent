# Architecture

## System Overview

A same-origin web app: a Next.js static-export frontend (served by FastAPI at `/app/`) and a FastAPI backend on port 8001. A user uploads a CSV; the backend validates it, runs an in-process EDA graph **synchronously inside the request**, persists the run outcome and the rendered HTML report in SQLite, and returns links the UI embeds and downloads. There is no worker queue, no external object store, and no separate database server in Phase 1.

## Component Map

```
Browser
  │  (same-origin, relative paths — no /api/v1 prefix)
  ▼
FastAPI (uvicorn, port 8001)
  ├─ /app/*   → Next.js static export (frontend/out/), mounted by FastAPI
  ├─ /health  → health check
  ├─ /runs*   → run lifecycle + report (src/api/runs.py)
  │
  ├─ Graph (in-process, src/graph/): ingest → profile → render_report → END
  │     ├─ profile  → src/tools/ (pandas profiling, matplotlib charts)
  │     ├─ render   → src/tools/ (self-contained HTML report)
  │     └─ narrative → Gemini (gemini-2.5-flash), derived stats only
  │
  └─ SQLite (SQLAlchemy 2.0) — run metadata + report HTML
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| UI | CSV upload, progress state, embedded report viewer + download, labelled Phase 2/3 stubs |
| API | Run lifecycle, report serving (HTML document) — no auth in Phase 1 |
| Agent/Graph | Orchestrates `ingest → profile → render_report` synchronously in-process |
| Tools | Pure functions: pandas profiling, matplotlib chart generation, HTML report rendering |
| Storage | SQLite for run metadata + the rendered report HTML |

## Data Flow

1. Trigger: user uploads a CSV via the UI or `POST /runs` (multipart, field `file`).
2. API validates the file (is CSV, non-empty, within size limit), creates a `Run` row.
3. The graph runs **synchronously** in the request: `ingest` (read + validate CSV into a DataFrame) → `profile` (derive aggregated stats, render 3 charts, call Gemini for the narrative with derived stats only, falling back to a template on error) → `render_report` (assemble the self-contained HTML).
4. The run row is updated with `status`, `narrative`, and `report_html`; the response returns `run_id`, `status`, `report_url`, `narrative`, `error`.
5. Frontend embeds the report from `GET /runs/{run_id}/report` (raw HTML) and offers a download.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Gemini (`gemini-2.5-flash`, `AGENT_GEMINI_API_KEY`) | Generate the narrative from derived aggregated stats only | Degrade to a templated narrative; the run still completes |
| SQLite (local file) | Run metadata + report HTML | Write failure surfaces as a run error (local disk) |

## Stack

- **Language:** Python 3.11+ (backend); TypeScript (frontend).
- **Agent framework:** LangGraph (`langgraph` package) used as an in-process `StateGraph` in `src/graph/` — synchronous, no external checkpointer.
- **LLM provider + model:** Google Gemini, model `gemini-2.5-flash`, key `AGENT_GEMINI_API_KEY` in `.env` (provider auto-detected from the key). Used **only** to generate the report narrative from derived, aggregated statistics — never raw rows. Accessed via `LLMClient().call_model(prompt, system=None)`.
- **Backend:** FastAPI (uvicorn), run with `uv run python -m src` → `src/__main__.py`, serving on **port 8001**; health at `GET /health`.
- **Database + ORM:** SQLite via SQLAlchemy 2.0. Tables created at startup by `init_db()` → `Base.metadata.create_all` (app lifespan). Default URL `sqlite:///./data/agent.db` (`AGENT_DATABASE_URL`). **No Alembic migrations are wired** — no migration step for the user.
- **Frontend:** Next.js 15 static export (`output: 'export'`, `basePath: '/app'`, `trailingSlash: true`), built with `cd frontend && pnpm build` → `frontend/out/`, mounted by FastAPI at `/app/`. UI and API are **same-origin**; the frontend calls relative paths (e.g. `/runs`) with **no `/api/v1` prefix**.
- **Dependency management:** uv (Python), pnpm (frontend).
- **Observability:** structured request/response logging (input, output summary, latency, error) to stdout via `structlog` — wired from Phase 1. (No LangSmith/OpenTelemetry/Prometheus in Phase 1.)

| Key library | Purpose |
|-------------|---------|
| FastAPI + uvicorn | HTTP API + server |
| SQLAlchemy 2.0 | SQLite ORM |
| langgraph | In-process graph orchestration |
| pandas | CSV profiling / EDA |
| matplotlib (Agg backend) | Chart rendering → base64 PNG |
| google-genai | Gemini client (narrative) |
| structlog | Structured logging |

**Avoid in Phase 1:** worker queues, distributed processing, and heavyweight MLOps stacks — kept out to keep Phase 1 the smallest testable win.

## Deferred to future phases

- **Postgres** (managed metadata store), **Redis + Celery/RQ** (worker queue for longer training runs), **S3 / object storage** (artifact store), and **auth (JWT/API key)** are all **out of Phase 1**. They may be introduced when Phase 2 (training) or Phase 3 (scheduling/delivery) is scoped, if load or requirements justify it — not before.

## Deployment Model

Single process: `uv run python -m src` serves both the API and the mounted static frontend on port 8001 against a local SQLite file. No separate worker, database server, or object store to provision in Phase 1.
