# Agent

This project uses a small pipeline-style agent built on **LangGraph** (`langgraph` package) as an in-process `StateGraph`. The graph models the EDA → reporting pipeline as discrete, deterministic nodes. It runs **synchronously inside the HTTP request** — there is no worker queue and no external checkpointer; the in-process state is transient and the outcome (status, narrative, report HTML) is persisted to the SQLite `runs` row.

---

## Agent Architecture Pattern

**Chosen:** Graph pipeline (LangGraph `StateGraph`) — a linear multi-step flow (`ingest → profile → render_report`) with a conditional error edge. Rationale: clean separation between ingesting, profiling, and rendering makes each step independently testable, and the conditional edge routes any failure to a single `handle_error` node.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `profile` (narrative sub-step) | Google Gemini | `gemini-2.5-flash` | Fast, low-cost summary generation; the only LLM use in the pipeline |

- Gemini is the **only** provider. Provider auto-detects from `AGENT_GEMINI_API_KEY`. Accessed via `LLMClient().call_model(prompt, system=None)`.
- The LLM is used **only** to turn derived, aggregated statistics into a human-readable narrative. It **never** receives raw dataset rows (PII rule).

**Fallback behaviour:** If the Gemini call errors or times out, the pipeline degrades to a **templated narrative** built from the same derived stats and still completes the run (status `completed`, narrative present, no crash). This is a production resilience path, not a test stub — tests call the real Gemini API with the key from `.env`.

**Prompt strategy:** System prompt in `src/prompts/narrative.md`. The user prompt contains only aggregated statistics (row/column counts, dtypes, missingness summary, numeric min/mean/max/std, top categoricals, strongest correlations) as compact text. Output is a short plain-text executive summary.

---

## Tools & Tool Calling

Tools are **pure functions** under `src/tools/`, invoked deterministically by the `profile`/`render_report` nodes (not LLM-selected).

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

**Reads from state:** the ingested DataFrame, `input_path`
**Writes to state:** `profile`, `narrative`, `status`, may set `error`
**LLM call:** yes — Gemini `gemini-2.5-flash`, derived aggregated stats only, plain-text output
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| `profile_dataframe`, `render_charts` tools | Compute stats + render 3 charts | fatal (set `error`) |
| Gemini | Generate narrative from derived stats | partial — fall back to templated narrative, continue |

**Behaviour:** Computes summary stats, missingness, sample rows, and renders the histogram/boxplot/correlation-heatmap charts (base64 PNG). Then calls Gemini with the derived stats to produce the narrative; on Gemini failure it builds a templated narrative and continues.

### `render_report`

**Reads from state:** `profile`, charts, `narrative`
**Writes to state:** `report_html`, `status`
**LLM call:** no
**External calls:** `render_report_html` tool (pure)
**Behaviour:** Assembles a single self-contained HTML document (stats table, missingness table, sample-rows table, 3 embedded charts, narrative). No external I/O.

### `train` (Phase 2 — deferred stub)

Not wired in Phase 1. In Phase 2 this node will train a scikit-learn model on a labeled CSV and persist a `ModelArtifact`. Documented here so the graph can be extended without restructuring.

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
render_report ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| ingest | `state.get("error")` set | handle_error |
| ingest | otherwise | profile |
| profile | `state.get("error")` set | handle_error |
| profile | otherwise | render_report |

(The Gemini narrative failure inside `profile` does NOT set `error` — it falls back to a template, so the flow proceeds to `render_report`.)

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
