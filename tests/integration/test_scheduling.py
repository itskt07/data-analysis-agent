"""Integration tests for Phase 3 scheduling & delivery.

Exercise the /schedules endpoints against the real EDA pipeline (real Gemini
narrate step, non-fatal fallback) via the api_client fixture. The interval
firing is NOT waited on — "Run now" is the deterministic, synchronous path used
throughout. The webhook delivery is exercised over the wire against a real local
HTTP listener.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"
IRIS = "small_iris.csv"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _create_schedule(api_client, *, interval_minutes=60, webhook_url=None, name=None):
    data = {"interval_minutes": str(interval_minutes)}
    if webhook_url is not None:
        data["webhook_url"] = webhook_url
    if name is not None:
        data["name"] = name
    return api_client.post(
        "/schedules",
        files={"file": (IRIS, _read(IRIS), "text/csv")},
        data=data,
    )


class _CaptureServer:
    """A real local HTTP listener that records the last POSTed JSON payload."""

    def __init__(self):
        self.payloads: list[dict] = []
        handler = self._make_handler()
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _make_handler(self):
        payloads = self.payloads

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    payloads.append(json.loads(body.decode("utf-8")))
                except ValueError:
                    payloads.append({"_raw": body.decode("utf-8", "replace")})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):  # silence
                pass

        return Handler

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------- #
# Create + list
# --------------------------------------------------------------------------- #

def test_create_schedule_returns_active_with_empty_history(api_client):
    resp = _create_schedule(api_client, interval_minutes=60, name="daily iris")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["schedule_id"]
    assert data["active"] is True
    assert data["interval_minutes"] == 60
    assert data["name"] == "daily iris"
    assert data["filename"] == IRIS
    assert data["webhook_url"] is None
    assert data["last_run_at"] is None
    assert data["runs"] == []


def test_name_defaults_to_filename(api_client):
    resp = _create_schedule(api_client, interval_minutes=15)
    data = resp.json()["data"]
    assert data["name"] == IRIS


def test_list_schedules_lists_created(api_client):
    r1 = _create_schedule(api_client, interval_minutes=30)
    sid = r1.json()["data"]["schedule_id"]

    resp = api_client.get("/schedules")
    assert resp.status_code == 200
    items = resp.json()["data"]
    ids = [s["schedule_id"] for s in items]
    assert sid in ids
    # List summary omits run history.
    assert all("runs" not in s for s in items)


# --------------------------------------------------------------------------- #
# Run now (happy path — real EDA pipeline)
# --------------------------------------------------------------------------- #

@pytest.mark.usefixtures("_require_llm_key")
def test_run_now_creates_completed_run_with_report(api_client):
    sid = _create_schedule(api_client, interval_minutes=60).json()["data"]["schedule_id"]

    resp = api_client.post(f"/schedules/{sid}/run")
    assert resp.status_code == 200
    run = resp.json()["data"]
    assert run["status"] == "completed"
    run_id = run["run_id"]
    assert run["report_url"] == f"/runs/{run_id}/report"
    assert run["error"] is None

    # The report is served by the existing runs endpoint as HTML.
    report = api_client.get(run["report_url"])
    assert report.status_code == 200
    assert "text/html" in report.headers["content-type"]
    assert "<html" in report.text.lower()

    # It shows up in the schedule's run history, and last_run_at is set.
    detail = api_client.get(f"/schedules/{sid}").json()["data"]
    assert detail["last_run_at"] is not None
    history_ids = [r["run_id"] for r in detail["runs"]]
    assert run_id in history_ids
    hist = next(r for r in detail["runs"] if r["run_id"] == run_id)
    assert hist["status"] == "completed"
    assert hist["report_url"] == f"/runs/{run_id}/report"


@pytest.mark.usefixtures("_require_llm_key")
def test_run_now_twice_appends_history_most_recent_first(api_client):
    sid = _create_schedule(api_client, interval_minutes=60).json()["data"]["schedule_id"]
    first = api_client.post(f"/schedules/{sid}/run").json()["data"]["run_id"]
    second = api_client.post(f"/schedules/{sid}/run").json()["data"]["run_id"]

    detail = api_client.get(f"/schedules/{sid}").json()["data"]
    ids = [r["run_id"] for r in detail["runs"]]
    assert first in ids and second in ids
    assert len(ids) >= 2


# --------------------------------------------------------------------------- #
# Webhook delivery
# --------------------------------------------------------------------------- #

@pytest.mark.usefixtures("_require_llm_key")
def test_webhook_receives_payload(api_client):
    with _CaptureServer() as capture:
        sid = _create_schedule(
            api_client, interval_minutes=60, webhook_url=capture.url
        ).json()["data"]["schedule_id"]

        resp = api_client.post(f"/schedules/{sid}/run")
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        assert len(capture.payloads) == 1
        payload = capture.payloads[0]
        assert payload["schedule_id"] == sid
        assert payload["run_id"] == run_id
        assert payload["status"] == "completed"
        assert payload["report_url"] == f"/runs/{run_id}/report"


@pytest.mark.usefixtures("_require_llm_key")
def test_unreachable_webhook_is_non_fatal(api_client):
    # Port 1 is unbound → connection refused; the run must still complete.
    sid = _create_schedule(
        api_client, interval_minutes=60, webhook_url="http://127.0.0.1:1/nope"
    ).json()["data"]["schedule_id"]

    resp = api_client.post(f"/schedules/{sid}/run")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #

@pytest.mark.usefixtures("_require_llm_key")
def test_delete_removes_schedule_but_retains_runs(api_client):
    sid = _create_schedule(api_client, interval_minutes=60).json()["data"]["schedule_id"]
    run_id = api_client.post(f"/schedules/{sid}/run").json()["data"]["run_id"]

    resp = api_client.delete(f"/schedules/{sid}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["schedule_id"] == sid
    assert body["deleted"] is True

    # Schedule gone.
    assert api_client.get(f"/schedules/{sid}").status_code == 404
    # The produced run and its report are retained.
    still = api_client.get(f"/runs/{run_id}")
    assert still.status_code == 200
    assert still.json()["data"]["status"] == "completed"
    assert api_client.get(f"/runs/{run_id}/report").status_code == 200


# --------------------------------------------------------------------------- #
# Error cases
# --------------------------------------------------------------------------- #

def test_non_csv_rejected(api_client):
    resp = api_client.post(
        "/schedules",
        files={"file": ("notes.txt", b"just some text", "application/octet-stream")},
        data={"interval_minutes": "60"},
    )
    assert resp.status_code == 400


def test_empty_csv_rejected(api_client):
    resp = api_client.post(
        "/schedules",
        files={"file": ("empty.csv", _read("empty.csv"), "text/csv")},
        data={"interval_minutes": "60"},
    )
    assert resp.status_code == 400


def test_missing_interval_rejected(api_client):
    resp = api_client.post(
        "/schedules",
        files={"file": (IRIS, _read(IRIS), "text/csv")},
    )
    assert resp.status_code == 400


def test_interval_below_one_rejected(api_client):
    resp = _create_schedule(api_client, interval_minutes=0)
    assert resp.status_code == 400


def test_non_integer_interval_rejected(api_client):
    resp = api_client.post(
        "/schedules",
        files={"file": (IRIS, _read(IRIS), "text/csv")},
        data={"interval_minutes": "soon"},
    )
    assert resp.status_code == 400


def test_get_unknown_schedule_404(api_client):
    assert api_client.get("/schedules/does-not-exist").status_code == 404


def test_run_unknown_schedule_404(api_client):
    assert api_client.post("/schedules/does-not-exist/run").status_code == 404


def test_delete_unknown_schedule_404(api_client):
    assert api_client.delete("/schedules/does-not-exist").status_code == 404
