"""Graph nodes for the training pipeline: ingest_train -> train -> evaluate ->
summarize -> persist.

Each node catches its own exceptions. Fatal errors (invalid file/target, fit or
evaluation failure) set ``state["error"]`` and route to ``handle_error``. The
``summarize`` (Gemini) step is the only non-fatal step: on any failure it falls
back to a templated insight and the run still completes.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from graph.train_state import TrainState
from llm.client import LLMClient
from tools.profiling import parse_csv
from tools.training import serialize_model, train_and_evaluate

logger = logging.getLogger("agent.train")

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "train_insight.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def ingest_train(state: TrainState) -> TrainState:
    """Validate + parse the uploaded CSV and confirm the target column exists."""
    try:
        df = parse_csv(state.get("csv_bytes") or b"")
        target = (state.get("target_column") or "").strip()
        if not target:
            raise ValueError("A target column must be specified.")
        if target not in df.columns:
            raise ValueError(
                f"Target column '{target}' is not a column in the uploaded CSV."
            )
        logger.info(
            "ingest_train ok train_id=%s rows=%d cols=%d target=%s",
            state.get("train_id"), df.shape[0], df.shape[1], target,
        )
        return {**state, "dataframe": df, "target_column": target}
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning(
            "ingest_train failed train_id=%s error=%s", state.get("train_id"), exc
        )
        return {**state, "error": str(exc)}


def train(state: TrainState) -> TrainState:
    """Detect the task, build + fit the pipeline, and evaluate on a held-out split."""
    try:
        result = train_and_evaluate(
            state["dataframe"],
            state["target_column"],
            state.get("algorithm") or "auto",
        )
        logger.info(
            "train ok train_id=%s task=%s algorithm=%s n_rows=%d features=%d",
            state.get("train_id"), result["task_type"], result["algorithm"],
            result["n_rows"], len(result["feature_columns"]),
        )
        return {
            **state,
            "task_type": result["task_type"],
            "algorithm": result["algorithm"],
            "model": result["pipeline"],
            "metrics": result["metrics"],
            "feature_columns": result["feature_columns"],
            "n_rows": result["n_rows"],
        }
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning("train failed train_id=%s error=%s", state.get("train_id"), exc)
        return {**state, "error": str(exc)}


def evaluate(state: TrainState) -> TrainState:
    """Serialize the fitted pipeline to joblib bytes (metrics computed in train)."""
    try:
        artifact_bytes = serialize_model(state["model"])
        logger.info(
            "evaluate ok train_id=%s artifact_bytes=%d",
            state.get("train_id"), len(artifact_bytes),
        )
        return {**state, "artifact_bytes": artifact_bytes}
    except Exception as exc:  # noqa: BLE001 - fatal, surface to handle_error
        logger.warning("evaluate failed train_id=%s error=%s", state.get("train_id"), exc)
        return {**state, "error": str(exc)}


def _metrics_summary(state: TrainState) -> str:
    """Compact aggregated-metrics text for the Gemini prompt (no raw rows)."""
    metrics = state.get("metrics") or {}
    lines = [
        f"Task type: {state.get('task_type')}.",
        f"Algorithm: {state.get('algorithm')}.",
        f"Target column: {state.get('target_column')}.",
        f"Feature columns ({len(state.get('feature_columns') or [])}): "
        f"{', '.join(state.get('feature_columns') or []) or 'none'}.",
        "",
        "Evaluation metrics (held-out test set):",
    ]
    for key, value in metrics.items():
        lines.append(f"  - {key}: {value}")
    return "\n".join(lines)


def _templated_insight(state: TrainState) -> str:
    """Deterministic fallback insight built from aggregated metrics only."""
    metrics = state.get("metrics") or {}
    task = state.get("task_type")
    algo = state.get("algorithm")
    n_test = metrics.get("n_test", "?")
    if task == "classification":
        headline = (
            f"A {algo} classifier was trained to predict "
            f"'{state.get('target_column')}' across {metrics.get('n_classes', '?')} "
            f"classes, reaching accuracy {metrics.get('accuracy')} and weighted "
            f"F1 {metrics.get('f1')} on {n_test} held-out test rows."
        )
    else:
        headline = (
            f"A {algo} regressor was trained to predict "
            f"'{state.get('target_column')}', reaching R² {metrics.get('r2')} with "
            f"MAE {metrics.get('mae')} and RMSE {metrics.get('rmse')} on {n_test} "
            f"held-out test rows."
        )
    return (
        f"{headline} (This summary was generated by the built-in template; the AI "
        "insight was unavailable.)"
    )


def summarize(state: TrainState) -> TrainState:
    """Generate a metrics insight via Gemini; fall back to a template on any error.

    Never fatal — an insight failure must not fail the run. Sends ONLY aggregated
    metrics + column/feature names to the LLM (PII rule — never raw cell values).
    """
    started = time.monotonic()
    try:
        system_prompt = _load_prompt()
        insight = LLMClient().call_model(_metrics_summary(state), system=system_prompt)
        insight = (insight or "").strip()
        if not insight:
            raise ValueError("Gemini returned an empty insight")
        logger.info(
            "summarize ok train_id=%s latency_ms=%d chars=%d",
            state.get("train_id"), int((time.monotonic() - started) * 1000), len(insight),
        )
        return {**state, "insight": insight}
    except Exception as exc:  # noqa: BLE001 - non-fatal, fall back to template
        logger.warning(
            "summarize fell back to template train_id=%s latency_ms=%d error=%s",
            state.get("train_id"), int((time.monotonic() - started) * 1000), exc,
        )
        return {**state, "insight": _templated_insight(state)}


def persist(state: TrainState) -> TrainState:
    """Write the completed training_runs row.

    The runner also reconciles the row after invoke (matching the EDA pattern);
    this node is the canonical write point.
    """
    from db.models import TrainingRow
    from db.session import create_db_session

    train_id = state.get("train_id")
    try:
        with create_db_session() as session:
            row = session.get(TrainingRow, train_id)
            if row is not None:
                row.status = "completed"
                row.filename = state.get("filename")
                row.target_column = state.get("target_column")
                row.algorithm = state.get("algorithm")
                row.task_type = state.get("task_type")
                row.metrics = json.dumps(state.get("metrics") or {})
                row.feature_columns = json.dumps(state.get("feature_columns") or [])
                row.artifact = state.get("artifact_bytes")
                row.n_rows = state.get("n_rows")
                row.n_features = len(state.get("feature_columns") or [])
                row.insight = state.get("insight")
                row.error_message = None
        logger.info("persist ok train_id=%s status=completed", train_id)
    except Exception as exc:  # noqa: BLE001 - persistence failure surfaces as error
        logger.warning("persist failed train_id=%s error=%s", train_id, exc)
        return {**state, "error": str(exc), "status": "failed"}
    return {**state, "status": "completed"}


def handle_error(state: TrainState) -> TrainState:
    logger.error(
        "training run failed train_id=%s error=%s",
        state.get("train_id"), state.get("error"),
    )
    return {**state, "status": "failed"}


# --- Edge functions -------------------------------------------------------

def after_ingest_train(state: TrainState) -> str:
    if state.get("error"):
        return "handle_error"
    return "train"


def after_train(state: TrainState) -> str:
    if state.get("error"):
        return "handle_error"
    return "evaluate"


def after_evaluate(state: TrainState) -> str:
    if state.get("error"):
        return "handle_error"
    return "summarize"
