"""Integration tests for the EDA pipeline — require the real Gemini key.

These exercise the full graph (ingest -> profile -> narrate -> render_report)
against the real Gemini API, plus the HTTP round-trip and edge/error cases.
"""
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from graph.runner import run_agent
from db import session as session_module
from db.models import RunRow

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _fetch(run_id: str) -> RunRow:
    with Session(session_module._engine) as s:
        return s.get(RunRow, run_id)


@pytest.mark.usefixtures("_require_llm_key")
def test_full_report_from_iris(_isolated_db):
    """Happy path: real Gemini narrative + full report with tables and 3 charts."""
    run_id = run_agent(_read("small_iris.csv"), "small_iris.csv")
    run = _fetch(run_id)

    assert run is not None
    assert run.status == "completed"
    assert run.error_message is None

    html = run.report_html
    assert html and "<!DOCTYPE html>" in html
    # Tables present.
    assert "Summary statistics" in html
    assert "Missingness" in html
    assert "Sample rows" in html
    assert "sepal_length" in html
    # Three base64 charts embedded.
    assert html.count("data:image/png;base64,") == 3
    # Narrative is real and non-trivial.
    assert run.narrative and len(run.narrative) > 30
    assert "built-in template" not in run.narrative


@pytest.mark.usefixtures("_require_llm_key")
def test_http_round_trip(api_client):
    """POST /runs multipart -> completed, then GET report -> HTML with charts."""
    resp = api_client.post(
        "/runs",
        files={"file": ("small_iris.csv", _read("small_iris.csv"), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["report_url"] == f"/runs/{data['run_id']}/report"
    assert data["narrative"]
    assert data["error"] is None

    report = api_client.get(data["report_url"])
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/html")
    body = report.text
    assert "Summary statistics" in body
    assert body.count("data:image/png;base64,") == 3


def test_non_csv_rejected(api_client):
    resp = api_client.post(
        "/runs",
        files={"file": ("notes.txt", b"just some text", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_empty_csv_rejected(api_client):
    resp = api_client.post(
        "/runs",
        files={"file": ("empty.csv", _read("empty.csv"), "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.usefixtures("_require_llm_key")
def test_categorical_only_still_completes(_isolated_db):
    """No numeric columns: report renders with a note; run completes."""
    run_id = run_agent(_read("categorical_only.csv"), "categorical_only.csv")
    run = _fetch(run_id)
    assert run.status == "completed"
    assert run.report_html
    assert "no numeric columns" in run.report_html.lower()
    # No numeric charts possible.
    assert run.report_html.count("data:image/png;base64,") == 0


@pytest.mark.usefixtures("_require_llm_key")
def test_single_column_still_completes(_isolated_db):
    """Single numeric column: histogram + boxplot render, heatmap omitted."""
    run_id = run_agent(_read("single_column.csv"), "single_column.csv")
    run = _fetch(run_id)
    assert run.status == "completed"
    assert run.report_html
    # Histogram + boxplot render; correlation heatmap needs >= 2 numeric cols.
    assert run.report_html.count("data:image/png;base64,") == 2


@pytest.mark.usefixtures("_require_llm_key")
def test_all_missing_column_still_completes(_isolated_db):
    """A fully-missing column must not crash profiling."""
    run_id = run_agent(_read("all_missing_column.csv"), "all_missing_column.csv")
    run = _fetch(run_id)
    assert run.status == "completed"
    assert run.report_html
    assert "notes" in run.report_html


def test_narrative_fallback_on_llm_failure(_isolated_db, monkeypatch):
    """If Gemini fails, the run still completes with a templated narrative."""
    from llm.client import LLMClient

    def _boom(self, prompt, *, system=None):
        raise RuntimeError("simulated Gemini outage")

    monkeypatch.setattr(LLMClient, "call_model", _boom)

    run_id = run_agent(_read("small_iris.csv"), "small_iris.csv")
    run = _fetch(run_id)
    assert run.status == "completed"
    assert run.report_html
    assert run.narrative
    assert "built-in template" in run.narrative
    assert run.report_html.count("data:image/png;base64,") == 3


@pytest.mark.usefixtures("_require_llm_key")
def test_get_unknown_run_404(api_client):
    resp = api_client.get("/runs/does-not-exist")
    assert resp.status_code == 404
