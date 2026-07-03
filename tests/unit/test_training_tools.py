"""Pure-function tests for the training tools — no LLM key required."""
import io

import joblib
import numpy as np
import pandas as pd
import pytest

from tools.training import (
    build_pipeline,
    infer_task_type,
    serialize_model,
    train_and_evaluate,
)
from graph.train_nodes import _metrics_summary


def _classification_df(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    f1 = rng.normal(0, 1, n)
    f2 = rng.normal(0, 1, n)
    cat = rng.choice(["p", "q", "r"], n)
    score = 2.0 * f1 - 1.5 * f2 + rng.normal(0, 0.3, n)
    q = np.quantile(score, [1 / 3, 2 / 3])
    label = np.where(score < q[0], "a", np.where(score < q[1], "b", "c"))
    return pd.DataFrame({"f1": f1, "f2": f2, "cat": cat, "label": label})


def _regression_df(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    x1 = rng.uniform(0, 10, n)
    x2 = rng.normal(0, 2, n)
    cat = rng.choice(["a", "b"], n)
    y = 3.0 * x1 - 2.0 * x2 + rng.normal(0, 0.5, n)
    return pd.DataFrame({"x1": x1, "x2": x2, "cat": cat, "target": y})


# --- infer_task_type -----------------------------------------------------

def test_infer_task_type_non_numeric_is_classification():
    assert infer_task_type(pd.Series(["yes", "no", "yes", "maybe"])) == "classification"


def test_infer_task_type_low_cardinality_int_is_classification():
    assert infer_task_type(pd.Series([0, 1, 0, 1, 1, 0] * 20)) == "classification"


def test_infer_task_type_continuous_float_is_regression():
    rng = np.random.default_rng(3)
    assert infer_task_type(pd.Series(rng.uniform(0, 100, 200))) == "regression"


def test_infer_task_type_high_cardinality_int_is_regression():
    # 200 distinct integers -> exceeds max(20, 5% of rows) -> regression.
    assert infer_task_type(pd.Series(range(200))) == "regression"


# --- build_pipeline ------------------------------------------------------

def test_build_pipeline_returns_resolved_algorithm_and_features():
    df = _classification_df()
    pipeline, resolved, features = build_pipeline(df, "label", "classification", "auto")
    assert resolved == "random_forest"
    assert set(features) == {"f1", "f2", "cat"}
    assert pipeline is not None


# --- train_and_evaluate: classification ----------------------------------

def test_train_and_evaluate_classification_metrics():
    df = _classification_df()
    result = train_and_evaluate(df, "label", "auto")
    assert result["task_type"] == "classification"
    assert result["algorithm"] == "random_forest"
    m = result["metrics"]
    for key in ("accuracy", "f1", "precision", "recall", "n_classes", "classes", "n_test"):
        assert key in m
    assert 0.0 <= m["accuracy"] <= 1.0
    assert m["n_test"] > 0
    assert m["n_classes"] == 3


def test_train_and_evaluate_logistic_regression_classification():
    df = _classification_df()
    result = train_and_evaluate(df, "label", "logistic_regression")
    assert result["task_type"] == "classification"
    assert result["algorithm"] == "logistic_regression"
    assert "accuracy" in result["metrics"]


# --- train_and_evaluate: regression --------------------------------------

def test_train_and_evaluate_regression_metrics():
    df = _regression_df()
    result = train_and_evaluate(df, "target", "auto")
    assert result["task_type"] == "regression"
    m = result["metrics"]
    for key in ("r2", "mae", "rmse", "n_test"):
        assert key in m
    assert m["n_test"] > 0
    # A strong linear signal should yield a decent R2 with random forest.
    assert m["r2"] > 0.5


def test_train_and_evaluate_linear_regression_counterpart():
    df = _regression_df()
    result = train_and_evaluate(df, "target", "logistic_regression")
    assert result["task_type"] == "regression"
    assert result["algorithm"] == "logistic_regression"
    assert result["metrics"]["r2"] > 0.8  # linear signal, linear model


# --- serialize round-trip ------------------------------------------------

def test_serialize_model_round_trip_predicts():
    df = _classification_df()
    result = train_and_evaluate(df, "label", "auto")
    raw = serialize_model(result["pipeline"])
    assert isinstance(raw, bytes) and len(raw) > 0
    loaded = joblib.load(io.BytesIO(raw))
    preds = loaded.predict(df[result["feature_columns"]].head(5))
    assert len(preds) == 5


# --- ValueError cases ----------------------------------------------------

def test_bad_target_raises():
    df = _classification_df()
    with pytest.raises(ValueError, match="not in the dataset"):
        train_and_evaluate(df, "nope", "auto")


def test_no_features_raises():
    df = pd.DataFrame({"only": [1, 2, 3, 4, 5, 6, 7, 8]})
    with pytest.raises(ValueError, match="no feature columns"):
        train_and_evaluate(df, "only", "auto")


def test_too_few_rows_raises():
    df = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "label": ["a", "b", "a"]})
    with pytest.raises(ValueError, match="Too few usable rows"):
        train_and_evaluate(df, "label", "auto")


def test_single_sample_class_raises():
    # A class with only one sample cannot be split/evaluated.
    df = pd.DataFrame(
        {
            "f1": [float(i) for i in range(10)],
            "label": ["a"] * 9 + ["b"],  # class "b" has a single sample
        }
    )
    with pytest.raises(ValueError):
        train_and_evaluate(df, "label", "auto")


def test_metrics_summary_excludes_raw_rows():
    """Privacy guard (spec PII rule): the Gemini insight prompt built by the
    `summarize` node must contain ONLY aggregated metrics + column names —
    never raw cell values. Mirrors the Phase-1 `narrate` prompt-spy.
    """
    n = 40
    df = pd.DataFrame(
        {
            # Sentinel raw values that must NEVER reach the LLM prompt.
            "feature_a": [f"SENTINELRAW{i}" for i in range(n)],
            "feature_b": [1_000_000 + i for i in range(n)],
            "label": (["low", "high"] * (n // 2)),
        }
    )
    result = train_and_evaluate(df, "label", "auto")
    state = {
        "task_type": result["task_type"],
        "algorithm": "auto",
        "target_column": "label",
        "feature_columns": result["feature_columns"],
        "metrics": result["metrics"],
    }
    summary = _metrics_summary(state)

    # Aggregates + column NAMES are allowed and present.
    assert "Evaluation metrics" in summary
    assert "feature_a" in summary and "feature_b" in summary

    # No raw cell VALUE leaks into the prompt.
    for i in range(n):
        assert f"SENTINELRAW{i}" not in summary, f"raw categorical leaked: row {i}"
        assert str(1_000_000 + i) not in summary, f"raw numeric leaked: row {i}"
