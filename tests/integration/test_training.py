"""Integration tests for the training pipeline — require the real Gemini key.

These exercise the full training graph (ingest_train -> train -> evaluate ->
summarize -> persist) against the real Gemini API, plus the HTTP round-trip and
edge/error cases.
"""
import io
from pathlib import Path

import joblib
import pytest
from sqlalchemy.orm import Session

from graph.train_runner import run_training
from db import session as session_module
from db.models import TrainingRow

FIXTURES = Path(__file__).parent.parent / "fixtures"

CLASSIFICATION_TARGET = "label"
REGRESSION_TARGET = "price"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _fetch(train_id: str) -> TrainingRow:
    with Session(session_module._engine) as s:
        return s.get(TrainingRow, train_id)


@pytest.mark.usefixtures("_require_llm_key")
def test_classification_run_completes(_isolated_db):
    """Happy path: classification training with real Gemini insight + artifact."""
    train_id = run_training(
        _read("train_classification.csv"), "train_classification.csv",
        CLASSIFICATION_TARGET, "auto",
    )
    row = _fetch(train_id)

    assert row is not None
    assert row.status == "completed"
    assert row.error_message is None
    assert row.task_type == "classification"

    import json
    metrics = json.loads(row.metrics)
    assert "accuracy" in metrics and "f1" in metrics
    assert "precision" in metrics and "recall" in metrics
    assert metrics["n_test"] >= 40

    # Artifact is present and joblib-loadable and can predict.
    assert row.artifact and len(row.artifact) > 0
    loaded = joblib.load(io.BytesIO(row.artifact))
    features = json.loads(row.feature_columns)
    import pandas as pd
    df = pd.read_csv(io.BytesIO(_read("train_classification.csv")))
    preds = loaded.predict(df[features].head(3))
    assert len(preds) == 3

    # Real insight present.
    assert row.insight and len(row.insight) > 10


@pytest.mark.usefixtures("_require_llm_key")
def test_regression_run_completes(_isolated_db):
    """Regression training produces r2/mae/rmse metrics."""
    train_id = run_training(
        _read("train_regression.csv"), "train_regression.csv",
        REGRESSION_TARGET, "auto",
    )
    row = _fetch(train_id)

    assert row.status == "completed"
    assert row.task_type == "regression"

    import json
    metrics = json.loads(row.metrics)
    assert "r2" in metrics and "mae" in metrics and "rmse" in metrics
    assert metrics["n_test"] >= 40


@pytest.mark.usefixtures("_require_llm_key")
@pytest.mark.parametrize("algorithm", ["logistic_regression", "random_forest"])
def test_both_algorithms_complete(_isolated_db, algorithm):
    train_id = run_training(
        _read("train_classification.csv"), "train_classification.csv",
        CLASSIFICATION_TARGET, algorithm,
    )
    row = _fetch(train_id)
    assert row.status == "completed"
    assert row.algorithm == algorithm
    assert row.task_type == "classification"
    assert row.artifact


@pytest.mark.usefixtures("_require_llm_key")
def test_http_round_trip(api_client):
    """POST /train multipart -> completed, then GET summary + artifact."""
    resp = api_client.post(
        "/train",
        files={"file": ("train_classification.csv", _read("train_classification.csv"), "text/csv")},
        data={"target_column": CLASSIFICATION_TARGET, "algorithm": "auto"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["task_type"] == "classification"
    assert data["artifact_url"] == f"/train/{data['train_id']}/artifact"
    assert "accuracy" in data["metrics"]
    assert data["error"] is None

    summary = api_client.get(f"/train/{data['train_id']}")
    assert summary.status_code == 200
    assert summary.json()["data"]["status"] == "completed"

    artifact = api_client.get(data["artifact_url"])
    assert artifact.status_code == 200
    assert artifact.headers["content-type"] == "application/octet-stream"
    assert len(artifact.content) > 0


def test_missing_target_rejected(api_client):
    resp = api_client.post(
        "/train",
        files={"file": ("train_classification.csv", _read("train_classification.csv"), "text/csv")},
    )
    assert resp.status_code == 400


def test_empty_target_rejected(api_client):
    resp = api_client.post(
        "/train",
        files={"file": ("train_classification.csv", _read("train_classification.csv"), "text/csv")},
        data={"target_column": "   "},
    )
    assert resp.status_code == 400


def test_target_not_a_column_rejected(api_client):
    resp = api_client.post(
        "/train",
        files={"file": ("train_classification.csv", _read("train_classification.csv"), "text/csv")},
        data={"target_column": "does_not_exist"},
    )
    assert resp.status_code == 400


def test_non_csv_rejected(api_client):
    resp = api_client.post(
        "/train",
        files={"file": ("notes.txt", b"just some text", "application/octet-stream")},
        data={"target_column": "label"},
    )
    assert resp.status_code == 400


def test_empty_csv_rejected(api_client):
    resp = api_client.post(
        "/train",
        files={"file": ("empty.csv", _read("empty.csv"), "text/csv")},
        data={"target_column": "label"},
    )
    assert resp.status_code == 400


def test_too_few_rows_rejected(api_client):
    tiny = b"f1,label\n1.0,a\n2.0,b\n"
    resp = api_client.post(
        "/train",
        files={"file": ("tiny.csv", tiny, "text/csv")},
        data={"target_column": "label"},
    )
    assert resp.status_code == 400


def test_get_unknown_train_404(api_client):
    resp = api_client.get("/train/does-not-exist")
    assert resp.status_code == 404


def test_artifact_unknown_404(api_client):
    resp = api_client.get("/train/does-not-exist/artifact")
    assert resp.status_code == 404


def test_summarize_fallback_on_llm_failure(_isolated_db, monkeypatch):
    """If Gemini fails, training still completes with a templated insight."""
    from llm.client import LLMClient

    def _boom(self, prompt, *, system=None):
        raise RuntimeError("simulated Gemini outage")

    monkeypatch.setattr(LLMClient, "call_model", _boom)

    train_id = run_training(
        _read("train_classification.csv"), "train_classification.csv",
        CLASSIFICATION_TARGET, "auto",
    )
    row = _fetch(train_id)
    assert row.status == "completed"
    assert row.insight
    assert "built-in template" in row.insight
    assert row.artifact
