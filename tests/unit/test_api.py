"""API contract tests — no LLM key required (graph is patched or not invoked)."""
from unittest.mock import patch

from sqlalchemy.orm import Session

from db.models import RunRow


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_post_runs_returns_report_url(api_client, _isolated_db):
    """POST /runs returns the envelope with report_url when a report exists."""
    with Session(_isolated_db) as s:
        row = RunRow(
            filename="data.csv",
            status="completed",
            narrative="Summary text.",
            report_html="<html>ok</html>",
        )
        s.add(row)
        s.commit()
        run_id = row.id

    with patch("api.runs.run_agent", return_value=run_id):
        r = api_client.post(
            "/runs",
            files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
        )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["run_id"] == run_id
    assert data["status"] == "completed"
    assert data["report_url"] == f"/runs/{run_id}/report"
    assert data["narrative"] == "Summary text."
    assert data["error"] is None


def test_post_runs_missing_file(api_client):
    r = api_client.post("/runs")
    assert r.status_code == 422


def test_post_runs_non_csv_rejected(api_client):
    r = api_client.post(
        "/runs",
        files={"file": ("notes.pdf", b"%PDF-1.4 binary", "application/pdf")},
    )
    assert r.status_code == 400


def test_post_runs_empty_file_rejected(api_client):
    r = api_client.post(
        "/runs",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert r.status_code == 400


def test_get_run_not_found(api_client):
    r = api_client.get("/runs/nonexistent-id")
    assert r.status_code == 404


def test_get_report_not_found(api_client):
    r = api_client.get("/runs/nonexistent-id/report")
    assert r.status_code == 404


def test_get_report_missing_for_failed_run(api_client, _isolated_db):
    with Session(_isolated_db) as s:
        row = RunRow(filename="bad.csv", status="failed", error_message="boom")
        s.add(row)
        s.commit()
        run_id = row.id

    r = api_client.get(f"/runs/{run_id}/report")
    assert r.status_code == 404
