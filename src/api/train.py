import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api._common import ok, api_error
from config.settings import get_settings
from db.session import get_session
from db.models import TrainingRow
from domain.training import TrainResponse
from graph.train_runner import run_training

router = APIRouter()


def _artifact_url(train_id: str) -> str:
    return f"/train/{train_id}/artifact"


def _loads(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _to_response(row: TrainingRow) -> dict:
    return TrainResponse(
        train_id=row.id,
        status=row.status,
        task_type=row.task_type,
        algorithm=row.algorithm,
        target_column=row.target_column,
        metrics=_loads(row.metrics),
        feature_columns=_loads(row.feature_columns),
        artifact_url=_artifact_url(row.id) if row.artifact else None,
        insight=row.insight,
        error=row.error_message,
    ).model_dump()


def _is_csv_upload(file: UploadFile) -> bool:
    name = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    if name.endswith(".csv"):
        return True
    return content_type in {"text/csv", "application/csv", "text/plain"}


@router.post("/train")
async def create_training(
    file: UploadFile = File(...),
    target_column: str | None = Form(None),
    algorithm: str = Form("auto"),
    session: Session = Depends(get_session),
) -> dict:
    if not _is_csv_upload(file):
        raise api_error("BAD_REQUEST", "Upload must be a CSV file.", 400)

    if not (target_column or "").strip():
        raise api_error("BAD_REQUEST", "A target column must be specified.", 400)

    file_bytes = await file.read()

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise api_error(
            "FILE_TOO_LARGE",
            f"File exceeds the {get_settings().max_upload_mb} MB limit.",
            413,
        )
    if not file_bytes or not file_bytes.strip():
        raise api_error("BAD_REQUEST", "The uploaded CSV is empty.", 400)

    train_id = run_training(
        file_bytes,
        file.filename or "upload.csv",
        target_column.strip(),
        (algorithm or "auto").strip().lower(),
    )
    row = session.get(TrainingRow, train_id)
    if row is None:
        raise api_error("NOT_FOUND", "Training run not found after creation", 500)

    # A training failure (bad target, too few rows, unusable data) is surfaced as
    # a 400 with the recorded error message; the row is retained as `failed`.
    if row.status == "failed":
        raise api_error("BAD_REQUEST", row.error_message or "Training failed.", 400)

    return ok(_to_response(row))


@router.get("/train/{train_id}")
def get_training(train_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(TrainingRow, train_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Training run {train_id} not found", 404)
    return ok(_to_response(row))


@router.get("/train/{train_id}/artifact")
def get_artifact(train_id: str, session: Session = Depends(get_session)) -> Response:
    row = session.get(TrainingRow, train_id)
    if row is None or not row.artifact:
        raise api_error("NOT_FOUND", f"Artifact for training run {train_id} not found", 404)
    return Response(
        content=row.artifact,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="model_{train_id}.joblib"'
        },
    )
