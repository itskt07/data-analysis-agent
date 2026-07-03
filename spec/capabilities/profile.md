# Capability: Profile Dataset (EDA + Report)

## What It Does
Ingests an uploaded CSV, runs automated exploratory data analysis, and produces a single self-contained HTML report with summary-statistics/missingness/sample-rows tables, 3 embedded charts, and an LLM-generated narrative. **(Phase 1)**

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | CSV (multipart) | `POST /runs` upload | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| report_html | self-contained HTML document | SQLite `runs.report_html`; served by `GET /runs/{run_id}/report` |
| narrative | string | `runs.narrative`; returned in the run response |
| status | `completed` / `failed` | `runs.status`; run response |

The report contains: a per-column summary-statistics table (dtype, count, missing count/%, numeric mean/std/min/max, categorical unique/top), a missingness table, a sample-rows table (first N rows), and 3 charts embedded as base64 PNG — a histogram (a numeric column), a boxplot (numeric columns), and a correlation heatmap (numeric columns).

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini (`gemini-2.5-flash`) | Generate the narrative from derived aggregated stats only (never raw rows) | Degrade to a templated narrative; the run still completes |
| SQLite | Persist run outcome + report HTML | Surface as a run error |

## Business Rules
- Raw dataset rows are NEVER sent to the LLM and NEVER persisted in the DB — only derived, aggregated statistics.
- The report is a single self-contained HTML document (charts embedded as base64 PNG) that opens offline.
- The run executes synchronously within the `POST /runs` request.
- Charts are rendered with matplotlib using the Agg backend.
- A file must be a non-empty CSV within the 50 MB limit; otherwise it is rejected before any analysis.
- Edge datasets (all-missing column, single column, non-numeric-only) still produce a valid report (charts that require numerics are omitted or shown empty, never crash).

## Success Criteria
- [ ] Uploading a fixture CSV via `POST /runs` returns `status: "completed"` with a non-null `report_url` and `narrative`.
- [ ] `GET /runs/{run_id}/report` returns an HTML document containing the summary table, missingness table, sample-rows table, and 3 base64-embedded PNG charts.
- [ ] The narrative is present even when the Gemini call fails (templated fallback), and the run still completes.
- [ ] A non-CSV upload is rejected with 400; an empty CSV is rejected with 400; a file over 50 MB is rejected with 413.
- [ ] A CSV with an all-missing column, a single column, or only non-numeric columns still produces a report (no crash).
- [ ] `uv run pytest tests/integration/test_pipeline.py -v` passes against the real Gemini key.
