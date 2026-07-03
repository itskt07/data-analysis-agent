"""Chart rendering for the EDA report.

All charts are rendered with matplotlib's headless Agg backend and returned as
base64-encoded PNG strings (without a data-URI prefix). Every function returns
``None`` gracefully when the data cannot support the chart (e.g. no numeric
columns), so the report renderer can note the omission rather than crash.
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")  # headless backend — must be set before pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

_MAX_BOXPLOT_COLS = 12


def _fig_to_base64(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=90, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("ascii")


def _numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.select_dtypes(include="number")


def histogram(df: pd.DataFrame) -> str | None:
    """Histogram of the first numeric column with any non-null values."""
    numeric = _numeric_frame(df)
    for column in numeric.columns:
        values = numeric[column].dropna()
        if values.empty:
            continue
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(values, bins=min(30, max(5, values.nunique())), color="#4c72b0", edgecolor="white")
        ax.set_title(f"Distribution of {column}")
        ax.set_xlabel(str(column))
        ax.set_ylabel("Frequency")
        return _fig_to_base64(fig)
    return None


def boxplot(df: pd.DataFrame) -> str | None:
    """Boxplot across all numeric columns (capped for readability)."""
    numeric = _numeric_frame(df)
    series = []
    labels = []
    for column in list(numeric.columns)[:_MAX_BOXPLOT_COLS]:
        values = numeric[column].dropna()
        if values.empty:
            continue
        series.append(values)
        labels.append(str(column))
    if not series:
        return None

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.boxplot(series, tick_labels=labels, showfliers=True)
    ax.set_title("Numeric column distributions")
    ax.set_ylabel("Value")
    if len(labels) > 3:
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    return _fig_to_base64(fig)


def correlation_heatmap(df: pd.DataFrame) -> str | None:
    """Pearson correlation heatmap of numeric columns (needs >= 2 columns)."""
    numeric = _numeric_frame(df)
    if numeric.shape[1] < 2:
        return None
    corr = numeric.corr(numeric_only=True)
    if corr.empty or corr.isna().all().all():
        return None

    fig, ax = plt.subplots(figsize=(6, 5))
    image = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels([str(c) for c in corr.columns], rotation=45, ha="right")
    ax.set_yticklabels([str(c) for c in corr.columns])
    ax.set_title("Correlation heatmap")

    n = len(corr.columns)
    for i in range(n):
        for j in range(n):
            value = corr.iloc[i, j]
            if pd.notna(value):
                ax.text(
                    j, i, f"{value:.2f}",
                    ha="center", va="center",
                    color="black", fontsize=8,
                )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    return _fig_to_base64(fig)


def render_charts(df: pd.DataFrame) -> dict[str, str | None]:
    """Render all three charts, returning a dict of base64 PNG strings (or None)."""
    return {
        "histogram": histogram(df),
        "boxplot": boxplot(df),
        "correlation_heatmap": correlation_heatmap(df),
    }
