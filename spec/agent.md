# Agent

This project uses a small pipeline-style agent built on **LangGraph** (`langgraph` package) as an in-process `StateGraph`. The graph models the EDA → reporting pipeline as discrete, deterministic nodes. It runs **synchronously inside the HTTP request** — there is no worker queue and no external checkpointer; the in-process state is transient and the outcome (status, narrative, report HTML) is persisted to the SQLite `runs` row.

---

## Agent Architecture Pattern

**Chosen:** Graph pipeline (LangGraph `StateGraph`) — a linear multi-step flow (`ingest → profile → narrate → render_report`) with a conditional error edge. Rationale: clean separation between ingesting, profiling (stats + charts), narrating (the single LLM step), and rendering makes each step independently testable, and the conditional edge routes any fatal failure to a single `handle_error` node.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `narrate` | Google Gemini | `gemini-2.5-flash` | Fast, low-cost summary generation; the only LLM use in the pipeline |

- Gemini is the **only** provider. Provider auto-detects from `AGENT_GEMINI_API_KEY`. Accessed via `LLMClient().call_model(prompt, system=None)`.
- The LLM is used **only** to turn derived, aggregated statistics into a human-readable narrative. It **never** receives raw dataset rows (PII rule).

**Fallback behaviour:** If the Gemini call errors or times out, the pipeline degrades to a **templated narrative** built from the same derived stats and still completes the run (status `completed`, narrative present, no crash). This is a production resilience path, not a test stub — tests call the real Gemini API with the key from `.env`.

**Prompt strategy:** System prompt in `src/prompts/narrative.md`. The user prompt contains only aggregated statistics (row/column counts, dtypes, missingness summary, numeric min/mean/max/std, top categoricals, strongest correlations) as compact text. Output is a short plain-text executive summary.

---

## Tools & Tool Calling

Tools are **pure functions** under `src/tools/`, invoked deterministically by the `profile`/`narrate`/`render_report` nodes (not LLM-selected).

| Tool | Description | Inputs | Output | Side-effects |
|------|-------------|--------|--------|--------------|
| `profile_dataframe` | Computes per-column summary stats, missingness, and sample rows | pandas DataFrame | derived-stats dict | none (pure) |
| `render_charts` | Renders histogram, boxplot, correlation heatmap (matplotlib Agg) | derived stats + DataFrame | dict of base64 PNG strings | none (pure) |
| `render_report_html` | Assembles a single self-contained HTML document | derived stats + charts + narrative | HTML string | none (pure) |

**Tool selection strategy:** Deterministic — each node calls its specific tool(s). No LLM tool routing.

**Tool failure handling:** A tool exception sets `state["error"]` and routes to `handle_error`. The Gemini narrative call is the one non-fatal step: its failure falls back to a template rather than failing the run.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                     # set at initialisation (SQLite runs.id)

    # Input
    input_path: str                 # path to the uploaded CSV on local disk
    filename: str                   # original uploaded filename

    # Pipeline data (populated progressively by nodes)
    profile: dict | None            # derived, aggregated statistics (never raw rows)

    # Output
    narrative: str | None           # Gemini narrative, or templated fallback
    report_html: str | None         # final self-contained HTML report

    # Control
    status: str                     # "pending" | "completed" | "failed"
    error: str | None               # set by any node on fatal failure
```

---

## Nodes / Steps

### `ingest`

**Reads from state:** `input_path`
**Writes to state:** `profile` is not written here; sets `status`, may set `error`
**LLM call:** no
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| Local disk | Read the uploaded CSV into a pandas DataFrame | fatal (set `error`) |

**Behaviour:** Reads and validates the CSV (parseable, non-empty). On a malformed/empty file sets `error`. The DataFrame is passed forward in-process; raw rows are never persisted or sent to the LLM.

### `profile`

**Reads from state:** the ingested DataFrame
**Writes to state:** `profile`, `charts`, may set `error`
**LLM call:** no
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| `profile_dataframe`, `render_charts` tools | Compute derived stats + render 3 charts | fatal (set `error`) |

**Behaviour:** Computes summary stats, missingness, and sample rows, and renders the histogram/boxplot/correlation-heatmap charts (base64 PNG). Pure/deterministic — no LLM call here. Routes to `narrate` on success, `handle_error` on failure.

### `narrate`

**Reads from state:** `profile`
**Writes to state:** `narrative` (never sets `error`)
**LLM call:** yes — Gemini `gemini-2.5-flash`, derived aggregated stats only (via `build_stats_summary`), plain-text output
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini | Generate narrative from derived stats | non-fatal — fall back to templated narrative, continue |

**Behaviour:** Builds a compact aggregated-stats summary (no raw rows) and calls Gemini to produce the executive-summary narrative. On any Gemini failure (error, timeout, empty response) it falls back to a templated narrative built from the same derived stats. This node is **never fatal** — it always proceeds to `render_report` with some narrative. This is the only LLM use in the pipeline.

### `render_report`

**Reads from state:** `profile`, `charts`, `narrative`
**Writes to state:** `report_html`, `status`
**LLM call:** no
**External calls:** `render_report_html` tool (pure)
**Behaviour:** Assembles a single self-contained HTML document (stats table, missingness table, sample-rows table, 3 embedded charts, narrative). No external I/O.

### `handle_error`

Sets `status="failed"`, keeps `error`, and logs context (structlog). Terminal.

---

## Graph / Flow Topology

```
START
  │
  ▼
ingest ──(error)──► handle_error ──► END
  │
  ▼
profile ──(error)──► handle_error ──► END
  │
  ▼
narrate ──► render_report ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| ingest | `state.get("error")` set | handle_error |
| ingest | otherwise | profile |
| profile | `state.get("error")` set | handle_error |
| profile | otherwise | narrate |

`narrate → render_report` and `render_report → END` are unconditional edges. The Gemini narrative failure inside `narrate` does NOT set `error` — it falls back to a template, so the flow always proceeds to `render_report`.

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | In-process LangGraph state | DataFrame, derived stats, charts, narrative, report HTML |
| **Across runs** | SQLite `runs` row | run id, status, filename, narrative, report HTML, error, timestamps — no raw rows |
| **Conversation** | none | Not a chat agent; each run is independent |

**Context window management:** N/A — the Gemini prompt contains only compact aggregated statistics, well within limits.

---

## Human-in-the-Loop Checkpoints

None in Phase 1 — the pipeline runs to completion synchronously. (A pre-promotion approval gate may be added for Phase 2 model training.)

---

## Error Handling & Recovery

**Node-level:** Each node catches its own exceptions; a fatal error sets `state["error"]` and the conditional edge routes to `handle_error`. The Gemini narrative call is the one non-fatal step (templated fallback).

**Graph-level (`handle_error`):** Sets `status="failed"`, preserves `error`, logs context; the API surfaces the error in the run response.

**Resume / retry strategy:** None in Phase 1 — runs are short and synchronous; a failed run is simply re-submitted.

**Partial failure:** Only the narrative degrades gracefully (template fallback). A profiling or rendering failure fails the run cleanly with a surfaced error (no crash).

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Run outcome** | Status, duration, error | SQLite + structured log (structlog, stdout) |
| **LLM call** | Prompt summary, latency, success/fallback | Structured log |
| **Request/response** | Endpoint, run_id, status, latency | Structured log |

No LangSmith / OpenTelemetry / Prometheus in Phase 1 — structured stdout logging only.

---

## Concurrency Model

Runs execute **synchronously** within their HTTP request; concurrency is handled by uvicorn's request handling (independent runs, independent SQLite rows). No worker pool, no node-level parallelism, no shared mutable state across runs in Phase 1.

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import ingest, profile, render_report, handle_error
from graph.edges import after_ingest, after_profile

def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("ingest", ingest)
    g.add_node("profile", profile)
    g.add_node("render_report", render_report)
    g.add_node("handle_error", handle_error)

    g.set_entry_point("ingest")
    g.add_conditional_edges(
        "ingest", after_ingest,
        {"profile": "profile", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "profile", after_profile,
        {"render_report": "render_report", "handle_error": "handle_error"},
    )
    g.add_edge("render_report", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()
```

---

## Phase 2 — Training Graph (dedicated `StateGraph`)

Model training uses a **second, separate LangGraph `StateGraph`**, mirroring the Phase-1 EDA structure but fully independent (its own state, nodes, runner, and DB table `training_runs`). It runs **synchronously inside the HTTP request** and is **deterministic/local** — scikit-learn does the work; the only LLM call is the non-fatal `summarize` step (analogous to `narrate` in the EDA graph). The EDA graph above is unchanged.

**Files:** `src/graph/train_state.py`, `src/graph/train_nodes.py`, `src/graph/train_agent.py`, `src/graph/train_runner.py`, `src/tools/training.py` (pure functions), `src/prompts/train_insight.md`.

### Training State (`src/graph/train_state.py`)

```python
class TrainState(TypedDict, total=False):
    # Identity
    train_id: str                   # set at initialisation (training_runs.id)

    # Input
    filename: str                   # original uploaded filename
    csv_bytes: bytes                # raw uploaded CSV, held in memory only
    target_column: str              # label column selected by the user
    algorithm: str                  # requested: "auto" | "logistic_regression" | "random_forest"

    # Pipeline data (populated progressively by nodes)
    task_type: str                  # "classification" | "regression" (detected)
    dataframe: object               # parsed pandas DataFrame (in-process only)
    model: object                   # fitted scikit-learn Pipeline
    feature_columns: list           # feature column names
    metrics: dict                   # evaluation metrics
    artifact_bytes: bytes           # joblib.dump(pipeline) bytes

    # Output
    insight: str | None             # Gemini metrics summary, or templated fallback

    # Control
    status: str                     # "pending" | "completed" | "failed"
    error: str | None               # set by any node on fatal failure
```

### Nodes / Steps

#### `ingest_train`
**Reads:** `csv_bytes`, `target_column`. **Writes:** `dataframe`, may set `error`. **LLM:** no.
Parses the CSV into a pandas DataFrame and validates it (parseable, non-empty; `target_column` must exist as a column; enough rows to train after dropping missing-target rows). Fatal on failure (set `error` → `handle_error`).

#### `train`
**Reads:** `dataframe`, `target_column`, `algorithm`. **Writes:** `task_type`, `model`, `feature_columns`, may set `error`. **LLM:** no.
Detects the task type deterministically, builds the preprocessing + estimator `Pipeline`, splits, and fits. Fatal on failure.

- **Task detection:** non-numeric target → `classification`. Numeric target: if integer-like AND unique-value count ≤ `max(20, 5% of rows)` → `classification`; else `regression`.
- **Algorithm mapping** (from requested `algorithm`):
  - classification: `logistic_regression` → `LogisticRegression(max_iter=1000)`; `random_forest` → `RandomForestClassifier`; `auto` → `RandomForestClassifier`.
  - regression: `logistic_regression` → `LinearRegression` (linear counterpart); `random_forest` → `RandomForestRegressor`; `auto` → `RandomForestRegressor`.
- **Preprocessing (`ColumnTransformer` inside the `Pipeline`, so the artifact predicts on raw-like rows):** drop rows with missing target; features = all columns except target; numeric → `SimpleImputer(strategy="median")` (+ `StandardScaler` for linear/logistic models only); categorical → `SimpleImputer(strategy="most_frequent")` + `OneHotEncoder(handle_unknown="ignore")`.
- **Split:** `train_test_split(test_size=0.25, random_state=42)`; `stratify=y` for classification when every class has ≥2 samples, else no stratify.

#### `evaluate`
**Reads:** `model`, `task_type`, test split. **Writes:** `metrics`, `artifact_bytes`, may set `error`. **LLM:** no.
Computes metrics on the held-out test set and serializes the fitted `Pipeline` to joblib bytes.

- classification metrics: `accuracy`, `f1` (weighted), `precision` (weighted), `recall` (weighted), `n_classes`, `classes`, `n_test`.
- regression metrics: `r2`, `mae`, `rmse`, `n_test`.
- `artifact_bytes` = `joblib.dump(pipeline)` to an in-memory buffer. Fatal on failure.

#### `summarize`
**Reads:** `metrics`, `feature_columns`, `target_column`, `task_type`, `algorithm`. **Writes:** `insight` (never sets `error`). **LLM:** yes — Gemini `gemini-2.5-flash`.
The **one non-fatal** step (mirrors `narrate`). Sends **only aggregated metrics + column/feature names** to Gemini (PII rule — never cell values) to produce a short plain-text insight. On any Gemini failure (error, timeout, empty) it falls back to a **templated insight** built from the same metrics and continues. System prompt in `src/prompts/train_insight.md`.

#### `persist`
**Reads:** all output fields. **Writes:** `status`. **LLM:** no.
Writes the `training_runs` row (status, filename, target_column, algorithm, task_type, metrics JSON, feature_columns JSON, `artifact` BLOB, n_rows, n_features, insight, error). Sets `status="completed"`. (In the runner, persistence may also be performed after `invoke`, matching the Phase-1 `run_agent` pattern; the node is the canonical write point.)

#### `handle_error`
Sets `status="failed"`, preserves `error`, logs context (structlog). Terminal. Reuses the same pattern as the EDA graph (a separate handler in the train graph).

### Graph / Flow Topology

```
START
  │
  ▼
ingest_train ──(error)──► handle_error ──► END
  │
  ▼
train ──(error)──► handle_error ──► END
  │
  ▼
evaluate ──(error)──► handle_error ──► END
  │
  ▼
summarize ──► persist ──► END
```

**Conditional edges:** `ingest_train`, `train`, and `evaluate` each route to `handle_error` when `state.get("error")` is set, otherwise to the next node. `summarize → persist` and `persist → END` are unconditional — the Gemini failure inside `summarize` does NOT set `error` (templated fallback), so the flow always reaches `persist`.

### Graph Assembly (`src/graph/train_agent.py`)

```python
from langgraph.graph import StateGraph, END

from graph.train_state import TrainState
from graph.train_nodes import (
    ingest_train, train, evaluate, summarize, persist, handle_error,
)
from graph.train_nodes import after_ingest_train, after_train, after_evaluate


def _build_graph() -> StateGraph:
    g = StateGraph(TrainState)
    g.add_node("ingest_train", ingest_train)
    g.add_node("train", train)
    g.add_node("evaluate", evaluate)
    g.add_node("summarize", summarize)
    g.add_node("persist", persist)
    g.add_node("handle_error", handle_error)

    g.set_entry_point("ingest_train")
    g.add_conditional_edges(
        "ingest_train", after_ingest_train,
        {"train": "train", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "train", after_train,
        {"evaluate": "evaluate", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "evaluate", after_evaluate,
        {"summarize": "summarize", "handle_error": "handle_error"},
    )
    g.add_edge("summarize", "persist")
    g.add_edge("persist", END)
    g.add_edge("handle_error", END)
    return g.compile()


training_ai = _build_graph()
```

The `train_runner.py` mirrors `runner.py`: it inserts a pending `training_runs` row, invokes `training_ai` with the initial `TrainState`, and reconciles the final status. Training is otherwise deterministic and local — no worker queue, no node-level parallelism.

---

## Phase 3 — Scheduling (no new graph)

Scheduled runs introduce **no new LangGraph graph and no new nodes**. A scheduled execution simply calls the existing EDA runner `run_agent(csv_bytes, filename)` (`src/graph/runner.py`), which invokes the unchanged `agentic_ai` EDA graph and creates a normal `runs` row. The only new machinery is an **in-process timer** that decides *when* to call `run_agent`, plus an optional webhook POST *after* it returns. The EDA and Train graphs above are untouched.

**Scheduler component (`src/scheduling/scheduler.py`):**
- Uses **APScheduler `BackgroundScheduler`** — a single module-level instance. NOT Celery/Redis/RQ; jobs run **in-process** in a background thread within the same uvicorn process, reusing the synchronous EDA pipeline. `apscheduler` is added to `pyproject.toml`.
- **`start()`** — called once from the FastAPI lifespan (`src/api/__init__.py`) after `init_db()`; starts the `BackgroundScheduler`.
- **`reregister_active()`** — called from the lifespan right after `start()`; loads every `active` `schedules` row from SQLite and adds an interval job for each (`trigger="interval", minutes=interval_minutes`, `id=schedule_id`, `replace_existing=True`). This is how schedule definitions survive a server restart. Missed fires while the process was down are **not** back-filled (documented limitation).
- **`register(schedule)` / `unregister(schedule_id)`** — add/remove a job when a schedule is created (`POST /schedules`) or deleted (`DELETE /schedules/{id}`).
- **`execute_schedule(schedule_id)`** — the job function each interval fires (and the same function **Run now** invokes synchronously). It: (1) loads the schedule's `csv_bytes` + `filename` from the DB, (2) calls `run_agent(csv_bytes, filename)` → new `runs.id`, (3) updates the schedule's `last_run_at` and links the run to the schedule (`runs.schedule_id`), (4) if `webhook_url` is set, POSTs `{schedule_id, run_id, status, report_url}` to it — **non-fatal**: any webhook error is caught and logged (`structlog`), the run is still recorded.

**"Run now" vs interval firing:** both paths call the identical `execute_schedule` logic. **Run now** (`POST /schedules/{id}/run`) runs it **synchronously inside the HTTP request** (like `POST /runs`) and returns the created run, so the caller/gate sees the result immediately without waiting for the interval. Interval firing runs it on the `BackgroundScheduler` thread. Because `execute_schedule` reuses the fully-synchronous EDA pipeline and independent DB sessions per run, the two paths never share mutable state.

**Concurrency note:** APScheduler's default job settings (`max_instances=1` per job, `coalesce=True`) prevent a slow EDA run from overlapping itself on the same schedule. Different schedules and ad-hoc `POST /runs` remain independent (independent `runs` rows, independent sessions), consistent with the Phase-1 concurrency model.

**Observability:** each scheduled/Run-now execution logs `schedule_id`, resulting `run_id`, status, latency, and webhook delivery outcome via `structlog` to stdout — same structured-logging discipline as Phases 1–2. No LangSmith/OpenTelemetry added.
