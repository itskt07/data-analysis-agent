from typing import Any, TypedDict


class TrainState(TypedDict, total=False):
    # Identity
    train_id: str                    # set at initialisation (training_runs.id)

    # Input
    filename: str                    # original uploaded filename
    csv_bytes: bytes                 # raw uploaded CSV, in-memory only (never persisted)
    target_column: str               # label column selected by the user
    algorithm: str                   # requested: "auto" | "logistic_regression" | "random_forest"

    # Pipeline data (populated progressively by nodes)
    task_type: str                   # "classification" | "regression" (detected)
    dataframe: Any                   # parsed pandas DataFrame (in-process only)
    model: Any                       # fitted scikit-learn Pipeline
    feature_columns: list[str]       # feature column names
    metrics: dict[str, Any]          # evaluation metrics (aggregated only)
    artifact_bytes: bytes            # joblib.dump(pipeline) bytes
    n_rows: int                      # usable rows after dropping missing-target rows

    # Output
    insight: str | None              # Gemini metrics summary, or templated fallback

    # Control
    status: str                      # "pending" | "completed" | "failed"
    error: str | None                # set by any node on fatal failure
