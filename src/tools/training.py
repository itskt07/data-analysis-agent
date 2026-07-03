"""Pure, deterministic training functions for the Phase-2 model-training flow.

None of these functions call an LLM or perform network I/O. They detect the task
type, build a scikit-learn ``Pipeline`` (preprocessing + estimator), fit, evaluate
on a held-out test split, and serialize the fitted pipeline to joblib bytes.

Everything here is deterministic (``random_state=42``) so tests are stable.
"""
from __future__ import annotations

import io
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Minimum usable rows (after dropping missing-target rows) to attempt training.
MIN_ROWS = 5

_LINEAR_ALGOS = {"logistic_regression"}


def infer_task_type(y: pd.Series) -> str:
    """Detect the task type from the target series.

    Non-numeric target -> ``classification``. Numeric target -> ``classification``
    if the values are integer-like AND the unique count is small
    (``<= max(20, 5% of rows)``), else ``regression``.
    """
    y = y.dropna()
    n = len(y)
    if n == 0:
        raise ValueError("The target column has no non-missing values.")

    if not pd.api.types.is_numeric_dtype(y):
        return "classification"

    values = y.to_numpy()
    integer_like = bool(np.all(np.equal(np.mod(values, 1), 0)))
    if not integer_like:
        return "regression"

    threshold = max(20, int(0.05 * n))
    unique = int(pd.Series(values).nunique())
    if unique <= threshold:
        return "classification"
    return "regression"


def _resolve_algorithm(algorithm: str, task_type: str) -> str:
    """Resolve the requested algorithm (incl. ``auto``) to a concrete name."""
    requested = (algorithm or "auto").strip().lower()
    if requested not in {"auto", "logistic_regression", "random_forest"}:
        raise ValueError(
            f"Unknown algorithm '{algorithm}'. Choose one of: auto, "
            "logistic_regression, random_forest."
        )
    if requested == "auto":
        return "random_forest"
    return requested


def _make_estimator(resolved: str, task_type: str):
    if task_type == "classification":
        if resolved == "logistic_regression":
            return LogisticRegression(max_iter=1000)
        return RandomForestClassifier(random_state=42)
    # regression
    if resolved == "logistic_regression":
        # LinearRegression is the linear counterpart for a regression task.
        return LinearRegression()
    return RandomForestRegressor(random_state=42)


def build_pipeline(
    df: pd.DataFrame,
    target_column: str,
    task_type: str,
    algorithm: str,
) -> tuple[Pipeline, str, list[str]]:
    """Build (but do not fit) the preprocessing + estimator pipeline.

    Returns ``(pipeline, resolved_algorithm, feature_columns)``.
    """
    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' is not in the dataset.")

    feature_columns = [c for c in df.columns if c != target_column]
    if not feature_columns:
        raise ValueError(
            "The dataset has no feature columns (only the target column is present)."
        )

    resolved = _resolve_algorithm(algorithm, task_type)
    is_linear = resolved in _LINEAR_ALGOS

    features = df[feature_columns]
    numeric_cols = list(features.select_dtypes(include="number").columns)
    categorical_cols = [c for c in feature_columns if c not in numeric_cols]

    numeric_steps: list[tuple[str, Any]] = [
        ("impute", SimpleImputer(strategy="median")),
    ]
    if is_linear:
        numeric_steps.append(("scale", StandardScaler()))
    numeric_pipe = Pipeline(numeric_steps)

    categorical_pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    transformers: list[tuple[str, Any, list[str]]] = []
    if numeric_cols:
        transformers.append(("numeric", numeric_pipe, numeric_cols))
    if categorical_cols:
        transformers.append(("categorical", categorical_pipe, categorical_cols))

    preprocessor = ColumnTransformer(transformers=transformers, remainder="drop")
    estimator = _make_estimator(resolved, task_type)

    pipeline = Pipeline(
        [
            ("preprocess", preprocessor),
            ("model", estimator),
        ]
    )
    return pipeline, resolved, feature_columns


def _classification_metrics(y_true, y_pred) -> dict[str, Any]:
    classes = sorted({str(c) for c in pd.unique(pd.Series(y_true).astype(str))})
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "f1": round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "precision": round(
            float(precision_score(y_true, y_pred, average="weighted", zero_division=0)), 4
        ),
        "recall": round(
            float(recall_score(y_true, y_pred, average="weighted", zero_division=0)), 4
        ),
        "n_classes": len(classes),
        "classes": classes,
        "n_test": int(len(y_true)),
    }


def _regression_metrics(y_true, y_pred) -> dict[str, Any]:
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return {
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(rmse, 4),
        "n_test": int(len(y_true)),
    }


def train_and_evaluate(
    df: pd.DataFrame,
    target_column: str,
    algorithm: str,
) -> dict[str, Any]:
    """Detect task, split, fit, and evaluate.

    Returns a dict with ``pipeline``, ``task_type``, ``algorithm`` (resolved),
    ``metrics``, ``feature_columns``, and ``n_rows``.

    Raises ``ValueError`` for unusable inputs (bad target, no features, too few
    rows, or a class too small to split).
    """
    from sklearn.model_selection import train_test_split

    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' is not in the dataset.")

    # Drop rows with a missing target — we cannot learn from them.
    df = df[df[target_column].notna()].reset_index(drop=True)
    n_rows = int(len(df))
    if n_rows < MIN_ROWS:
        raise ValueError(
            f"Too few usable rows to train: {n_rows} (need at least {MIN_ROWS})."
        )

    feature_columns = [c for c in df.columns if c != target_column]
    if not feature_columns:
        raise ValueError(
            "The dataset has no feature columns (only the target column is present)."
        )

    y_full = df[target_column]
    task_type = infer_task_type(y_full)

    if task_type == "classification":
        # Coerce labels to strings for stable, hashable class handling.
        y_full = y_full.astype(str)

    X = df[feature_columns]

    stratify = None
    if task_type == "classification":
        counts = y_full.value_counts()
        if len(counts) < 2:
            raise ValueError(
                "Classification needs at least 2 distinct target classes; "
                f"found {len(counts)}."
            )
        if counts.min() < 2:
            raise ValueError(
                "Every class needs at least 2 samples to train and evaluate; "
                "at least one class has a single sample."
            )
        if bool((counts >= 2).all()):
            stratify = y_full

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_full, test_size=0.25, random_state=42, stratify=stratify
        )
    except ValueError as exc:
        raise ValueError(f"Could not split the data for training: {exc}") from exc

    if len(X_train) < 1 or len(X_test) < 1:
        raise ValueError("Too few rows to form a train/test split.")

    pipeline, resolved, feature_columns = build_pipeline(
        df, target_column, task_type, algorithm
    )
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    if task_type == "classification":
        metrics = _classification_metrics(y_test, y_pred)
    else:
        metrics = _regression_metrics(y_test, y_pred)

    return {
        "pipeline": pipeline,
        "task_type": task_type,
        "algorithm": resolved,
        "metrics": metrics,
        "feature_columns": feature_columns,
        "n_rows": n_rows,
    }


def serialize_model(pipeline: Pipeline) -> bytes:
    """Serialize a fitted pipeline to joblib bytes (in-memory buffer)."""
    buffer = io.BytesIO()
    joblib.dump(pipeline, buffer)
    return buffer.getvalue()
