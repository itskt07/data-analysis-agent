"""Pure profiling functions for the EDA pipeline.

None of these functions perform I/O beyond parsing in-memory bytes, and none
send data anywhere. The returned profile dict is fully JSON-serializable and
contains only derived, aggregated statistics plus a small sample of rows (the
sample is used ONLY to render the report tables — it is never sent to the LLM).
"""
from __future__ import annotations

import io
import math
from typing import Any

import pandas as pd

# Number of rows shown in the "sample rows" table of the report.
SAMPLE_ROW_COUNT = 10


def parse_csv(file_bytes: bytes) -> pd.DataFrame:
    """Parse raw CSV bytes into a DataFrame.

    Raises ValueError on empty input or an unparseable / column-less file.
    """
    if not file_bytes or not file_bytes.strip():
        raise ValueError("The uploaded file is empty.")

    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except pd.errors.EmptyDataError as exc:
        raise ValueError("The CSV contains no columns or rows.") from exc
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as ValueError
        raise ValueError(f"Could not parse the file as CSV: {exc}") from exc

    if df.shape[1] == 0:
        raise ValueError("The CSV contains no columns.")
    if df.shape[0] == 0:
        raise ValueError("The CSV contains a header but no data rows.")

    return df


def parse_parquet(file_bytes: bytes) -> pd.DataFrame:
    """Parse raw Parquet bytes into a DataFrame.

    Raises ValueError on empty input or an unparseable / column-less file.
    """
    if not file_bytes:
        raise ValueError("The uploaded file is empty.")

    try:
        df = pd.read_parquet(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as ValueError
        raise ValueError(f"Could not parse the file as Parquet: {exc}") from exc

    if df.shape[1] == 0:
        raise ValueError("The Parquet file contains no columns.")
    if df.shape[0] == 0:
        raise ValueError("The Parquet file contains no data rows.")

    return df


def parse_dataset(file_bytes: bytes, filename: str | None = None) -> pd.DataFrame:
    """Parse uploaded bytes into a DataFrame, dispatching by file extension.

    Supports CSV (the default) and Parquet (``.parquet`` / ``.pq``). Both paths
    raise ValueError on empty/unparseable/column-less input so the ingest node
    can surface a clean error.
    """
    name = (filename or "").lower()
    if name.endswith(".parquet") or name.endswith(".pq"):
        return parse_parquet(file_bytes)
    return parse_csv(file_bytes)


def _clean_number(value: Any) -> float | int | None:
    """Coerce a numpy/pandas scalar to a JSON-safe python number (or None)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    # Preserve integers without spurious ".0".
    if f.is_integer():
        return int(f)
    return round(f, 4)


def _stringify(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Build a JSON-serializable profile dict of aggregated statistics."""
    n_rows = int(df.shape[0])
    numeric_cols = list(df.select_dtypes(include="number").columns)
    numeric_set = set(numeric_cols)

    columns: list[dict[str, Any]] = []
    missingness: list[dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        missing = int(series.isna().sum())
        non_null = int(series.notna().sum())
        missing_pct = round((missing / n_rows) * 100, 2) if n_rows else 0.0
        is_numeric = name in numeric_set

        col: dict[str, Any] = {
            "name": str(name),
            "dtype": str(series.dtype),
            "count": non_null,
            "missing": missing,
            "missing_pct": missing_pct,
            "kind": "numeric" if is_numeric else "categorical",
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "q25": None,
            "q50": None,
            "q75": None,
            "unique": None,
            "top": None,
            "top_freq": None,
        }

        if is_numeric and non_null > 0:
            col["mean"] = _clean_number(series.mean())
            col["std"] = _clean_number(series.std())
            col["min"] = _clean_number(series.min())
            col["max"] = _clean_number(series.max())
            col["q25"] = _clean_number(series.quantile(0.25))
            col["q50"] = _clean_number(series.quantile(0.50))
            col["q75"] = _clean_number(series.quantile(0.75))
        else:
            col["unique"] = int(series.nunique(dropna=True))
            value_counts = series.value_counts(dropna=True)
            if not value_counts.empty:
                col["top"] = _stringify(value_counts.index[0])
                col["top_freq"] = int(value_counts.iloc[0])

        columns.append(col)
        missingness.append(
            {"name": str(name), "missing": missing, "missing_pct": missing_pct}
        )

    sample_df = df.head(SAMPLE_ROW_COUNT)
    sample_rows = {
        "columns": [str(c) for c in df.columns],
        "rows": [[_stringify(v) for v in row] for row in sample_df.itertuples(index=False)],
    }

    correlations = _strongest_correlations(df, numeric_cols)

    return {
        "shape": {"rows": n_rows, "columns": int(df.shape[1])},
        "columns": columns,
        "numeric_columns": [str(c) for c in numeric_cols],
        "categorical_columns": [
            str(c) for c in df.columns if c not in numeric_set
        ],
        "missingness": missingness,
        "sample_rows": sample_rows,
        "correlations": correlations,
    }


def _strongest_correlations(
    df: pd.DataFrame, numeric_cols: list[Any], limit: int = 5
) -> list[dict[str, Any]]:
    """Return the strongest pairwise Pearson correlations among numeric columns."""
    if len(numeric_cols) < 2:
        return []
    try:
        corr = df[numeric_cols].corr(numeric_only=True)
    except Exception:  # noqa: BLE001 - correlation is best-effort for the narrative
        return []

    pairs: list[dict[str, Any]] = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = _clean_number(corr.iloc[i, j])
            if r is None:
                continue
            pairs.append({"a": str(cols[i]), "b": str(cols[j]), "r": r})

    pairs.sort(key=lambda p: abs(p["r"]), reverse=True)
    return pairs[:limit]
