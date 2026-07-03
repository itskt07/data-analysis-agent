from typing import Any

from pydantic import BaseModel


class TrainResponse(BaseModel):
    train_id: str
    status: str
    task_type: str | None = None
    algorithm: str | None = None
    target_column: str | None = None
    metrics: dict[str, Any] | None = None
    feature_columns: list[str] | None = None
    artifact_url: str | None = None
    insight: str | None = None
    error: str | None = None
