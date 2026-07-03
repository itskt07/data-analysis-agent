import json
import logging
import time

from graph.train_agent import training_ai
from graph.train_state import TrainState
from db.session import create_db_session, init_db
from db.models import TrainingRow

logger = logging.getLogger("agent.train_runner")


def run_training(
    file_bytes: bytes,
    filename: str,
    target_column: str,
    algorithm: str = "auto",
) -> str:
    """Run the training pipeline synchronously and persist the outcome.

    Returns the train_id. The uploaded bytes are held in memory only for the
    duration of the run; raw rows are never persisted (only the fitted model
    artifact and aggregated metrics are stored).
    """
    init_db()

    with create_db_session() as session:
        run = TrainingRow(
            filename=filename,
            target_column=target_column,
            algorithm=algorithm or "auto",
            status="pending",
        )
        session.add(run)
        session.flush()
        train_id = run.id

    started = time.monotonic()
    initial: TrainState = {
        "train_id": train_id,
        "filename": filename,
        "csv_bytes": file_bytes,
        "target_column": target_column,
        "algorithm": algorithm or "auto",
        "status": "pending",
        "error": None,
    }
    final = training_ai.invoke(initial)

    status = final.get("status", "completed")
    if final.get("error"):
        status = "failed"

    # Reconcile the row from the final state (idempotent with the persist node).
    with create_db_session() as session:
        row = session.get(TrainingRow, train_id)
        if row is not None:
            row.status = status
            row.target_column = final.get("target_column") or target_column
            row.algorithm = final.get("algorithm") or (algorithm or "auto")
            row.task_type = final.get("task_type")
            metrics = final.get("metrics")
            row.metrics = json.dumps(metrics) if metrics is not None else None
            features = final.get("feature_columns")
            row.feature_columns = json.dumps(features) if features is not None else None
            row.artifact = final.get("artifact_bytes")
            row.n_rows = final.get("n_rows")
            row.n_features = len(features) if features is not None else None
            row.insight = final.get("insight")
            row.error_message = final.get("error")

    logger.info(
        "training run complete train_id=%s status=%s latency_ms=%d",
        train_id, status, int((time.monotonic() - started) * 1000),
    )
    return train_id
